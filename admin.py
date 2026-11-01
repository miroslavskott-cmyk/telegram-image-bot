"""Admin-only /admin command. Silent for everyone except ADMIN_ID."""
import re

from telegram import Update
from telegram.ext import ContextTypes

import config

MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

HELP = (
    "الأوامر:\n"
    "/admin stats — الإحصائيات\n"
    "/admin pause — إيقاف التوليد مؤقتاً\n"
    "/admin resume — استئناف التوليد\n"
    "/admin model <اسم> — تغيير النموذج\n"
    "/admin limit <عدد> — الحد اليومي لكل مستخدم (0 = بلا حد من البوت)\n"
    "/admin maxlen <عدد> — أقصى طول للوصف (20–2000)\n"
    "/admin ban <id> — حظر مستخدم\n"
    "/admin unban <id> — إلغاء الحظر"
)


def _stats_text(db) -> str:
    s = db.stats()
    state = "⏸️ متوقف مؤقتاً" if db.get_setting("paused") == "1" else "▶️ يعمل"
    return (
        "📊 الإحصائيات\n"
        f"👥 المستخدمون: {s['users']} (محظورون: {s['banned']})\n"
        f"🎨 الطلبات: {s['requests']} (✅ {s['ok']} / ❌ {s['fail']})\n"
        f"الحالة: {state}\n"
        f"🧠 النموذج: {db.get_setting('model')}\n"
        f"📅 الحد اليومي: {db.get_int('daily_limit')}\n"
        f"✏️ أقصى طول للوصف: {db.get_int('max_prompt_len')}\n\n" + HELP
    )


def _to_int(text: str, low: int, high: int):
    try:
        value = int(text)
    except ValueError:
        return None
    return value if low <= value <= high else None


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.id != config.ADMIN_ID or update.message is None:
        return  # ignore silently: do not reveal that the command exists
    db = context.application.bot_data["db"]
    args = context.args or []
    cmd = args[0].lower() if args else "stats"
    arg = args[1] if len(args) > 1 else ""
    reply = update.message.reply_text

    if cmd == "stats":
        await reply(_stats_text(db))
    elif cmd == "pause":
        db.set_setting("paused", "1")
        await reply("⏸️ تم إيقاف التوليد للمستخدمين (المشرف مستثنى).")
    elif cmd == "resume":
        db.set_setting("paused", "0")
        await reply("▶️ تم استئناف التوليد.")
    elif cmd == "model":
        if not MODEL_RE.match(arg):
            await reply("اكتب اسم نموذج صالحاً، مثال: /admin model flux")
            return
        db.set_setting("model", arg)
        await reply(f"✅ النموذج الحالي: {arg}")
    elif cmd == "limit":
        value = _to_int(arg, 0, 10000)
        if value is None:
            await reply("مثال: /admin limit 20  (0 = بلا حد)")
            return
        db.set_setting("daily_limit", str(value))
        await reply(f"✅ الحد اليومي: {value}")
    elif cmd == "maxlen":
        value = _to_int(arg, 20, 2000)
        if value is None:
            await reply("مثال: /admin maxlen 800  (بين 20 و2000)")
            return
        db.set_setting("max_prompt_len", str(value))
        await reply(f"✅ أقصى طول للوصف: {value}")
    elif cmd in ("ban", "unban"):
        target = _to_int(arg, 1, 10**15)
        if target is None or target == config.ADMIN_ID:
            await reply("مثال: /admin ban 123456789")
            return
        if db.set_banned(target, cmd == "ban"):
            await reply("🚫 تم الحظر." if cmd == "ban" else "✅ أُلغي الحظر.")
        else:
            await reply("هذا المستخدم غير موجود في قاعدة البيانات.")
    else:
        await reply(HELP)
