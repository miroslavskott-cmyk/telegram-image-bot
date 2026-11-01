"""Image providers. To switch provider, add a subclass and register it in build_provider()."""
import asyncio
import logging
import random
from abc import ABC, abstractmethod
from urllib.parse import quote

import httpx

log = logging.getLogger("image_provider")


class ImageError(Exception):
    """code: timeout | rate | server | auth | balance | rejected | failed"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, model: str, width: int, height: int) -> bytes:
        """Return raw image bytes or raise ImageError."""

    async def close(self) -> None:
        return None


def _retry_after(resp: httpx.Response, default: float) -> float:
    try:
        return min(float(resp.headers.get("retry-after", default)), 30.0)
    except ValueError:
        return default


class PollinationsProvider(ImageProvider):
    """GET {base}/image/{prompt}?model=&width=&height=&seed=  (Bearer API key)."""

    def __init__(self, api_key: str, base_url: str, timeout: int, retries: int = 3):
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._retries = retries
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=True
        )

    async def generate(self, prompt: str, model: str, width: int, height: int) -> bytes:
        url = f"{self._base}/image/{quote(prompt, safe='')}"
        params = {
            "model": model,
            "width": width,
            "height": height,
            "seed": random.randint(0, 2**31 - 1),
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        error = "server"
        for attempt in range(1, self._retries + 1):
            delay = 2.0 * attempt
            try:
                resp = await self._client.get(url, params=params, headers=headers)
            except httpx.TimeoutException:
                error = "timeout"
                if attempt >= 2:
                    break
            except httpx.HTTPError as exc:
                log.warning("Network error: %s", type(exc).__name__)
                error = "server"
            else:
                status = resp.status_code
                ctype = resp.headers.get("content-type", "")
                if status == 200 and ctype.startswith("image/") and len(resp.content) > 1000:
                    return resp.content
                log.warning("Provider returned HTTP %s", status)
                if status in (401, 403):
                    raise ImageError("auth")
                if status == 402:
                    raise ImageError("balance")
                if status in (400, 422):
                    raise ImageError("rejected")
                if status == 429:
                    error = "rate"
                    delay = _retry_after(resp, 5.0 * attempt)
                elif status >= 500 or status == 200:
                    error = "server"
                else:
                    raise ImageError("failed")
            if attempt < self._retries:
                await asyncio.sleep(delay)
        raise ImageError(error)

    async def close(self) -> None:
        await self._client.aclose()


def build_provider(cfg) -> ImageProvider:
    if cfg.IMAGE_PROVIDER == "pollinations":
        return PollinationsProvider(cfg.IMAGE_API_KEY, cfg.IMAGE_BASE_URL, cfg.REQUEST_TIMEOUT)
    raise ValueError(f"Unknown IMAGE_PROVIDER: {cfg.IMAGE_PROVIDER}")
