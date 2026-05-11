from telegram import Update
from telegram.ext import ContextTypes

DESCRIPTION = "Приветствие и справка"


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Multi-Agent Bot</b>\n\n"
        "Доступные команды:\n\n"
        "/prian — парсинг prian.ru (недвижимость за рубежом)\n"
        "/help — список всех команд\n\n"
        "Просто отправьте ссылку prian.ru — бот сам определит и спарсит.",
        parse_mode="HTML",
    )