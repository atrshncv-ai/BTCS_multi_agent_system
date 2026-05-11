#!/usr/bin/env python3
"""
Avito Parser Telegram Bot - v5
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = "REDACTED_TELEGRAM_BOT_TOKEN"
RESULT_DIR = Path("/Users/aiserver/OPENCLAW BOT/parser_avito/result")
RESULT_DIR.mkdir(exist_ok=True)
pending_parses = {}


def is_avito_url(url):
    return "avito.ru" in url.lower()


async def start_command(update, context):
    await update.message.reply_text(
        "🔗 /parse - запустить парсинг", parse_mode="Markdown"
    )


async def parse_command(update, context):
    pending_parses[update.effective_user.id] = True
    await update.message.reply_text(
        "🔗 *Avito Parser*\n📎 Отправьте ссылку на Avito\n\n/parse",
        parse_mode="Markdown",
    )


async def handle_url(update, context):
    user_id = update.effective_user.id
    url = update.message.text.strip()

    if user_id not in pending_parses:
        return

    if not is_avito_url(url):
        await update.message.reply_text("❌ Только Avito", parse_mode="Markdown")
        return

    del pending_parses[user_id]
    status = await update.message.reply_text(f"⏳ Парсинг...", parse_mode="Markdown")

    try:
        result = await run_parser(url)
        
        xlsx_path = result.get("xlsx")
        
        if xlsx_path and Path(xlsx_path).exists():
            # Check if file has content
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_path, read_only=True)
            ws = wb.active
            row_count = sum(1 for _ in ws.rows)
            wb.close()
            
            with open(xlsx_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"✅ Готово!\n📊 {row_count-1} строк\n⏱️ {result.get('duration', 0)}сек",
                    parse_mode="Markdown"
                )
        else:
            msg = "Файл не создан. Возможные причины: прокси заблокирован, нет объявлений, таймаут. Попробуй другую ссылку"
            await status.edit_text(msg, parse_mode="Markdown")
                f"⚠️ Файл не создан\n\nВозможные причины:\n- Прокси заблокирован\n- Нет объявлений\n- Таймаут\n\nПопробуй другую ссылку",
                parse_mode="Markdown"
            )

    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}", parse_mode="Markdown")


async def run_parser(url):
    loop = asyncio.get_event_loop()

    def _run():
        import time
        import os

        start = time.time()

        # List existing files before running
        before = set(RESULT_DIR.glob("*.xlsx"))

        try:
            cmd = [
                "/Users/aiserver/OPENCLAW BOT/venv_parse/bin/python",
                "/Users/aiserver/OPENCLAW BOT/parser_avito/parser_cls.py",
                "--url",
                url,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd="/Users/aiserver/OPENCLAW BOT/parser_avito",
            )

            # Get newest file from after run
            all_files = list(RESULT_DIR.glob("*.xlsx"))
            new_files = [f for f in all_files if f not in before]

            if new_files:
                latest = max(new_files, key=lambda p: p.stat().st_mtime)
                return {
                    "status": "done",
                    "duration": round(time.time() - start, 1),
                    "xlsx": str(latest),
                }

            # Fallback: get any xlsx if none new
            if all_files:
                latest = max(all_files, key=lambda p: p.stat().st_mtime)
                return {
                    "status": "done",
                    "duration": round(time.time() - start, 1),
                    "xlsx": str(latest),
                }

            return {"status": "no_file", "duration": round(time.time() - start, 1)}

        except Exception as e:
            return {
                "status": "error",
                "duration": round(time.time() - start, 1),
                "error": str(e),
            }

    return await loop.run_in_executor(None, _run)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("parse", parse_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    print("🤖 Bot started")
    app.run_polling(drop_pending_updates=True, timeout=10)


if __name__ == "__main__":
    main()
