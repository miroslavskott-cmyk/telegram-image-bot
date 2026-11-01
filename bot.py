"""Telegram AI image generator bot (long polling)."""
import asyncio
import logging
import time

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from admin import admin_command
from database import Database
from image_provider import ImageError, build_provider

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
# These libraries log full request URLs (which contain the bot token) at INFO level.
for _name in ("httpx", "httpcore", "telegram", "apscheduler"):
    logging.getLogger(_name).setLevel(logging.WARNING)
log = logging.getLogger("bot")

RATIOS = {"square": ("1:1", 1024, 1024), "wide": ("16:9", 1344, 768), "tall": ("9:16", 768, 1344)}
STYLES = {
    "auto": ("Auto", ""),
    "photo": ("📷 Photo", ", highly realistic photograph, professional photography, natural lighting, sharp focus, high detail"),
    "cinematic": ("🎬 Cinematic", ", cinematic still, dramatic lighting, film grain, shallow depth of field, anamorphic lens"),
    "art": ("🎨 Art", ", detailed digital painting, illustration, vibrant colors, highly detailed"),
    "design": ("✏️ Design", ", clean graphic design, vector illustration, flat colors, minimal composition"),
}

TEXTS = {
    "ar": {
        "start": "👋 أهلاً بك!\n\nأرسل لي وصفاً نصياً (عربي أو English أو Français) وسأحوّله إلى صورة بالذكاء الاصطناعي.\n\nمثال:\nA realistic photo of a sports car in Algiers at sunset\n\nللمساعدة: /help",
        "help": "الأوامر:\n/generate <وصف> — توليد صورة\n/settings — أبعاد الصورة والأسلوب\n/help — هذه الرسالة\n\nيمكنك أيضاً إرسال الوصف مباشرة بدون أمر.\nالحد اليومي: {limit} صورة (0 = بلا حد من البوت). أقصى طول للوصف: {maxlen} حرفاً.",
        "working": "⏳ جاري إنشاء صورتك...",
        "busy": "⏳ لديك طلب قيد المعالجة، انتظر حتى ينتهي.",
        "paused": "⏸️ التوليد متوقف مؤقتاً. حاول لاحقاً.",
        "banned": "🚫 لا يمكنك استخدام هذا البوت.",
        "quota": "⚠️ وصلت إلى حدك اليومي ({limit} صورة). يتجدد الحد يومياً (توقيت UTC).",
        "too_long": "⚠️ الوصف طويل ({n} حرفاً). الحد الأقصى {max} حرفاً.",
        "empty": "أرسل وصف الصورة بعد الأمر، مثال:\n/generate a red fox in the snow",
        "settings": "⚙️ اختر أبعاد الصورة والأسلوب:",
        "err_timeout": "❌ انتهت مهلة خدمة التوليد. حاول مجدداً (لم يُحتسب الطلب).",
        "err_rate": "❌ الخدمة مزدحمة الآن. حاول بعد قليل (لم يُحتسب الطلب).",
        "err_server": "❌ خدمة التوليد لا تستجيب حالياً. حاول لاحقاً (لم يُحتسب الطلب).",
        "err_auth": "❌ البوت غير مهيأ بشكل صحيح حالياً. تم إبلاغ المشرف.",
        "err_balance": "❌ رصيد خدمة التوليد انتهى مؤقتاً. تم إبلاغ المشرف.",
        "err_rejected": "❌ رفضت الخدمة هذا الوصف. جرّب صياغة مختلفة (لم يُحتسب الطلب).",
        "err_failed": "❌ تعذر إنشاء الصورة. حاول مجدداً (لم يُحتسب الطلب).",
    },
    "en": {
        "start": "👋 Welcome!\n\nSend me a text description (English, Arabic or French) and I'll turn it into an AI-generated image.\n\nExample:\nA realistic photo of a sports car in Algiers at sunset\n\nHelp: /help",
        "help": "Commands:\n/generate <prompt> — generate an image\n/settings — image size and style\n/help — this message\n\nYou can also just send the description without a command.\nDaily limit: {limit} images (0 = no bot-side limit). Max prompt length: {maxlen} characters.",
        "working": "⏳ Creating your image...",
        "busy": "⏳ You already have a request in progress. Please wait.",
        "paused": "⏸️ Generation is temporarily paused. Try again later.",
        "banned": "🚫 You cannot use this bot.",
        "quota": "⚠️ You reached your daily limit ({limit} images). It resets daily (UTC).",
        "too_long": "⚠️ Prompt too long ({n} characters). Maximum is {max}.",
        "empty": "Send the description after the command, e.g.:\n/generate a red fox in the snow",
        "settings": "⚙️ Choose image size and style:",
        "err_timeout": "❌ The generation service timed out. Try again (not counted against your quota).",
        "err_rate": "❌ The service is busy. Try again shortly (not counted).",
        "err_server": "❌ The generation service is not responding. Try later (not counted).",
        "err_auth": "❌ The bot is not configured correctly right now. The admin was notified.",
        "err_balance": "❌ The generation service credit ran out temporarily. The admin was notified.",
        "err_rejected": "❌ The service rejected this prompt. Try rephrasing (not counted).",
        "err_failed": "❌ Could not create the image. Try again (not counted).",
    },
    "fr": {
        "start": "👋 Bienvenue !\n\nEnvoyez-moi une description (français, anglais ou arabe) et je la transforme en image par IA.\n\nExemple :\nA realistic photo of a sports car in Algiers at sunset\n\nAide : /help",
        "help": "Commandes :\n/generate <description> — générer une image\n/settings — format et style\n/help — ce message\n\nVous pouvez aussi envoyer directement la description.\nLimite quotidienne : {limit} images (0 = pas de limite côté bot). Longueur max : {maxlen} caractères.",
        "working": "⏳ Création de votre image...",
        "busy": "⏳ Vous avez déjà une demande en cours. Patientez.",
        "paused": "⏸️ La génération est temporairement suspendue. Réessayez plus tard.",
        "banned": "🚫 Vous ne pouvez pas utiliser ce bot.",
        "quota": "⚠️ Limite quotidienne atteinte ({limit} images). Elle se renouvelle chaque jour (UTC).",
        "too_long": "⚠️ Description trop longue ({n} caractères). Maximum : {max}.",
        "empty": "Envoyez la description après la commande, ex. :\n/generate a red fox in the snow",
        "settings": "⚙️ Choisissez le format et le style :",
        "err_timeout": "❌ Le service a expiré. Réessayez (non décompté).",
        "err_rate": "❌ Service saturé. Réessayez dans un instant (non décompté).",
        "err_server": "❌ Le service ne répond pas. Réessayez plus tard (non décompté).",
        "err_auth": "❌ Le bot n'est pas configuré correctement. L'admin a été prévenu.",
        "err_balance": "❌ Crédit du service épuisé temporairement. L'admin a été prévenu.",
        "err_rejected": "❌ Description refusée par le service. Reformulez (non décompté).",
        "err_failed": "❌ Impossible de créer l'image. Réessayez (non décompté).",
    },
}


def lang_of(user) -> str:
    code = ((user.language_code if user else "") or "en")[:2].lower()
    return code if code in TEXTS else "en"


def tr(lang: str, key: str, **kw) -> str:
    return TEXTS[lang][key].format(**kw) if kw else TEXTS[lang][key]


def settings_markup(ratio: str, style: str) -> InlineKeyboardMarkup:
    ratio_row = [
        InlineKeyboardButton(("✅ " if k == ratio else "") + v[0], callback_data=f"r:{k}")
        for k, v in RATIOS.items()
    ]
    styles = [
        InlineKeyboardButton(("✅ " if k == style else "") + v[0], callback_data=f"s:{k}")
        for k, v in STYLES.items()
    ]
    return InlineKeyboardMarkup([ratio_row, styles[:3], styles[3:]])


async def post_init(app: Application) -> None:
    app.bot_data["db"] = Database(config.DB_PATH, config.DEFAULT_MODEL)
    app.bot_data["provider"] = build_provider(config)
    app.bot_data["sem"] = asyncio.Semaphore(config.MAX_CONCURRENT)
    app.bot_data["active"] = set()
    app.bot_data["last_alert"] = 0.0
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Start"),
                BotCommand("generate", "Generate an image"),
                BotCommand("settings", "Size and style"),
                BotCommand("help", "Help"),
            ]
        )
    except TelegramError as exc:
        log.warning("set_my_commands failed: %s", type(exc).__name__)
    log.info("Bot started")


async def post_shutdown(app: Application) -> None:
    provider = app.bot_data.get("provider")
    if provider:
        await provider.close()
    log.info("Bot stopped")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    db.touch_user(update.effective_user.id)
    await update.message.reply_text(tr(lang_of(update.effective_user), "start"))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    await update.message.reply_text(
        tr(
            lang_of(update.effective_user),
            "help",
            limit=db.get_int("daily_limit"),
            maxlen=db.get_int("max_prompt_len"),
        )
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    uid = update.effective_user.id
    db.touch_user(uid)
    row = db.get_user(uid)
    await update.message.reply_text(
        tr(lang_of(update.effective_user), "settings"),
        reply_markup=settings_markup(row["ratio"], row["style"]),
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    db: Database = context.application.bot_data["db"]
    await query.answer()
    kind, _, value = (query.data or "").partition(":")
    uid = query.from_user.id
    db.touch_user(uid)
    if kind == "r" and value in RATIOS:
        db.set_pref(uid, "ratio", value)
    elif kind == "s" and value in STYLES:
        db.set_pref(uid, "style", value)
    else:
        return
    row = db.get_user(uid)
    try:
        await query.edit_message_reply_markup(settings_markup(row["ratio"], row["style"]))
    except TelegramError:
        pass  # "message is not modified" etc.


async def alert_admin(context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    """Tell the admin about provider auth/balance problems (max once per hour)."""
    data = context.application.bot_data
    if time.time() - data["last_alert"] < 3600:
        return
    data["last_alert"] = time.time()
    try:
        await context.bot.send_message(
            config.ADMIN_ID, f"⚠️ مشكلة في مزود الصور: {code} — تحقق من IMAGE_API_KEY أو الرصيد."
        )
    except TelegramError:
        pass


async def run_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:
    user = update.effective_user
    msg = update.effective_message
    data = context.application.bot_data
    db: Database = data["db"]
    lang = lang_of(user)
    is_admin = user.id == config.ADMIN_ID

    db.touch_user(user.id)
    if db.is_banned(user.id):
        await msg.reply_text(tr(lang, "banned"))
        return
    if db.get_setting("paused") == "1" and not is_admin:
        await msg.reply_text(tr(lang, "paused"))
        return

    prompt = " ".join(prompt.split())
    if not prompt:
        await msg.reply_text(tr(lang, "empty"))
        return
    max_len = db.get_int("max_prompt_len")
    if len(prompt) > max_len:
        await msg.reply_text(tr(lang, "too_long", n=len(prompt), max=max_len))
        return

    active: set = data["active"]
    if user.id in active:
        await msg.reply_text(tr(lang, "busy"))
        return
    active.add(user.id)

    reserved = False
    wait_msg = None
    try:
        limit = 0 if is_admin else db.get_int("daily_limit")
        ok, _ = db.reserve(user.id, limit)
        if not ok:
            await msg.reply_text(tr(lang, "quota", limit=limit))
            return
        reserved = True

        wait_msg = await msg.reply_text(tr(lang, "working"))
        try:
            await msg.chat.send_action(ChatAction.UPLOAD_PHOTO)
        except TelegramError:
            pass

        row = db.get_user(user.id)
        _, width, height = RATIOS.get(row["ratio"], RATIOS["square"])
        final_prompt = prompt + STYLES.get(row["style"], STYLES["auto"])[1]

        async with data["sem"]:
            image = await data["provider"].generate(
                final_prompt, db.get_setting("model"), width, height
            )

        caption = ("🎨 " + prompt)[:900]
        try:
            await msg.reply_photo(photo=image, caption=caption)
        except TelegramError:
            # e.g. photo too large for sendPhoto: send as a file instead
            await msg.reply_document(document=image, filename="image.jpg", caption=caption)
        db.record_result(True)
        reserved = False  # consumed successfully
        try:
            await wait_msg.delete()
        except TelegramError:
            pass
    except ImageError as exc:
        db.record_result(False)
        if reserved:
            db.refund(user.id)
        if exc.code in ("auth", "balance"):
            await alert_admin(context, exc.code)
        text = tr(lang, f"err_{exc.code}")
        await _show_error(msg, wait_msg, text)
    except Exception as exc:  # never let one user's error stop the bot
        log.error("Unexpected error: %s", type(exc).__name__)
        db.record_result(False)
        if reserved:
            db.refund(user.id)
        await _show_error(msg, wait_msg, tr(lang, "err_failed"))
    finally:
        active.discard(user.id)


async def _show_error(msg, wait_msg, text: str) -> None:
    try:
        if wait_msg is not None:
            await wait_msg.edit_text(text)
        else:
            await msg.reply_text(text)
    except TelegramError:
        pass


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args or [])
    if not prompt.strip():
        await update.message.reply_text(tr(lang_of(update.effective_user), "empty"))
        return
    await run_generation(update, context, prompt)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_generation(update, context, update.message.text or "")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error: %s", type(context.error).__name__)


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^[rs]:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_message)
    )
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
