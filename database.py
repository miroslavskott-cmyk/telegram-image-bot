"""SQLite storage: users, quotas, counters and runtime settings."""
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

DEFAULT_SETTINGS = {
    "paused": "0",
    "daily_limit": "20",  # per user, 0 = no bot-side limit
    "max_prompt_len": "800",
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Database:
    def __init__(self, path: str, default_model: str):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_seen INTEGER NOT NULL,
                    last_used INTEGER,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    daily_count INTEGER NOT NULL DEFAULT 0,
                    daily_date TEXT NOT NULL DEFAULT '',
                    banned INTEGER NOT NULL DEFAULT 0,
                    ratio TEXT NOT NULL DEFAULT 'square',
                    style TEXT NOT NULL DEFAULT 'auto'
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            defaults = dict(DEFAULT_SETTINGS, model=default_model)
            for key, value in defaults.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value)
                )
            self._conn.commit()

    # ---- settings / counters -------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    def get_int(self, key: str) -> int:
        try:
            return int(self.get_setting(key, DEFAULT_SETTINGS.get(key, "0")))
        except ValueError:
            return int(DEFAULT_SETTINGS.get(key, "0"))

    def incr(self, key: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, '1') "
                "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1",
                (key,),
            )
            self._conn.commit()

    # ---- users ---------------------------------------------------------------
    def touch_user(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users(user_id, first_seen) VALUES(?, ?) "
                "ON CONFLICT(user_id) DO NOTHING",
                (user_id, int(time.time())),
            )
            self._conn.commit()

    def get_user(self, user_id: int):
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM users WHERE user_id=?", (user_id,)
            ).fetchone()

    def is_banned(self, user_id: int) -> bool:
        row = self.get_user(user_id)
        return bool(row and row["banned"])

    def set_banned(self, user_id: int, banned: bool) -> bool:
        """Return False if the user is unknown."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def set_pref(self, user_id: int, field: str, value: str) -> None:
        if field not in ("ratio", "style"):
            raise ValueError("invalid field")
        with self._lock:
            self._conn.execute(
                f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id)
            )
            self._conn.commit()

    # ---- quota ---------------------------------------------------------------
    def reserve(self, user_id: int, limit: int):
        """Try to use one request from today's quota. Returns (ok, used_today)."""
        today = _today()
        with self._lock:
            row = self._conn.execute(
                "SELECT daily_count, daily_date FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            used = row["daily_count"] if row and row["daily_date"] == today else 0
            if limit > 0 and used >= limit:
                return False, used
            self._conn.execute(
                "UPDATE users SET daily_count=?, daily_date=?, "
                "total_requests=total_requests+1, last_used=? WHERE user_id=?",
                (used + 1, today, int(time.time()), user_id),
            )
            self._conn.commit()
            return True, used + 1

    def refund(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET daily_count=MAX(daily_count-1, 0) "
                "WHERE user_id=? AND daily_date=?",
                (user_id, _today()),
            )
            self._conn.commit()

    def record_result(self, ok: bool) -> None:
        self.incr("ok" if ok else "fail")

    # ---- stats ---------------------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            users = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned = self._conn.execute(
                "SELECT COUNT(*) FROM users WHERE banned=1"
            ).fetchone()[0]
            total = self._conn.execute(
                "SELECT COALESCE(SUM(total_requests), 0) FROM users"
            ).fetchone()[0]
        return {
            "users": users,
            "banned": banned,
            "requests": total,
            "ok": int(self.get_setting("ok", "0") or 0),
            "fail": int(self.get_setting("fail", "0") or 0),
        }
