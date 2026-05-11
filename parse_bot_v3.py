#!/usr/bin/env python3
"""
Avito Parser Telegram Bot v3 - с retry логикой
"""

import asyncio
import logging
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
        "🔗 *Avito Parser*\n\n/parse для запуска", parse_mode="Markdown"
    )


async def parse_command(update, context):
    pending_parses[update.effective_user.id] = True
    await update.message.reply_text(
        "🔗 *Avito Parser*\n📎 Отправьте ссылку:\nhttps://www.avito.ru/...\n\n⏳5 страниц",
        parse_mode="Markdown",
    )


async def handle_url(update, context):
    user_id = update.effective_user.id
    url = update.message.text.strip()

    if user_id not in pending_parses:
        return

    if not is_avito_url(url):
        await update.message.reply_text("❌ Только Avito ссылки", parse_mode="Markdown")
        return

    del pending_parses[user_id]
    status = await update.message.reply_text(
        f"⏳ Парсинг: {url[:30]}...", parse_mode="Markdown"
    )

try:
        result = await run_parser(url)
        
        if result.get("listings"):
            await send_result(update, result)
        else:
            # Even if no listings - try to send the xlsx file
            latest_xlsx = max(RESULT_DIR.glob("*.xlsx"), default=None, key=lambda p: p.stat().st_mtime)
            if latest_xlsx:
                await send_result(update, {"listings": [{}], "excel_path": str(latest_xlsx), "duration": result.get("duration", 0)})
            else:
                await status.edit_text(
                    f"⚠️ Файл не создан\nВремя: {result.get('duration', 0)}сек",
                    parse_mode="Markdown"
                )
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}", parse_mode="Markdown")
                )

            print(f"Return code: {result.returncode}")
            print(f"Stdout: {result.stdout[-300:]}")
            if result.stderr:
                print(f"Stderr: {result.stderr[-300:]}")

            items = []

            for xlsx in RESULT_DIR.glob("*.xlsx"):
                try:
                    import openpyxl

                    wb = openpyxl.load_workbook(xlsx, read_only=True)
                    for ws in wb.sheetnames:
                        for row in ws.iter_rows(values_only=True):
                            if row and row[0]:
                                items.append(
                                    {
                                        "title": str(row[0])[:200],
                                        "price": str(row[1]) if len(row) > 1 else "",
                                        "location": str(row[2]) if len(row) > 2 else "",
                                        "url": str(row[3]) if len(row) > 3 else "",
                                    }
                                )
                    wb.close()
                    print(f"Read {len(items)} from {xlsx.name}")
                except Exception as e:
                    print(f"Read error: {e}")

            latest_xlsx = max(
                RESULT_DIR.glob("*.xlsx"), default=None, key=lambda p: p.stat().st_mtime
            )

            return {
                "status": "success" if items else "empty",
                "listings": items[:200],
                "excel_path": str(latest_xlsx) if latest_xlsx else None,
                "duration": round(time.time() - start, 1),
            }

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "listings": [], "duration": 90}
        except Exception as e:
            import traceback

            return {
                "status": "error",
                "listings": [],
                "duration": round(time.time() - start, 1),
                "errors": [str(e)],
            }

    return await loop.run_in_executor(None, _run)


async def send_result(update, result):
    excel_path = result.get("excel_path")

    if excel_path and Path(excel_path).exists():
        with open(excel_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                caption=f"✅ Готово!\n📊 {len(result.get('listings', []))} объявлений\n⏱️ {result.get('duration', 0)}сек",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            f"⚠️ Файл не найден. Попробуй ещё раз /parse", parse_mode="Markdown"
        )


async def error_handler(update, context):
    logger.error(f"Update error: {context.error}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("parse", parse_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_error_handler(error_handler)

    print("🤖 Bot started")
    app.run_polling(drop_pending_updates=True, timeout=10)


if __name__ == "__main__":
    main()
