from telegram import Update
from telegram.ext import ContextTypes

DESCRIPTION = "Парсинг prian.ru (зарубежная недвижимость)"


async def prian_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if not args:
        await update.message.reply_text(
            "🔍 <b>Prian Parser</b>\n\n"
            "Использование: <code>/prian &lt;url&gt;</code>\n\n"
            "Поддерживает:\n"
            "• <a href='https://prian.ru/turkey/'>Страны</a>\n"
            "• <a href='https://prian.ru/search/'>Поиск с фильтрами</a>\n"
            "• <a href='https://prian.ru/company/'>Каталог компаний</a>\n"
            "• <a href='https://prian.ru/price/spain-33186-4136329.html'>Карточки объектов</a>",
            parse_mode="HTML",
        )
        return

    url = " ".join(args).strip()

    if not url.startswith("http"):
        await update.message.reply_text("❌ Укажите полную URL-ссылку prian.ru")
        return

    from extensions.prian_parser import parse_prian, is_valid_prian_url

    if not is_valid_prian_url(url):
        await update.message.reply_text("❌ Это не ссылка prian.ru")
        return

    await update.message.reply_text("🔍 Парсинг prian.ru...")
    try:
        result = parse_prian(url, max_items=50, max_pages=3)
        records = result.get("records", [])
        csv_path = result.get("csv_path", "")

        if records and csv_path:
            with open(csv_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"✅ Prian: {len(records)} объектов",
                )
            import os
            os.remove(csv_path)
        else:
            await update.message.reply_text("❌ Объекты не найдены. Проверьте ссылку.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")