#!/usr/bin/env python3
"""
Avito Parser Telegram Bot - v2 with pagination
"""

import os
import sys
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

TOKEN = ""

PARSER_DIR = Path("/Users/aiserver/OPENCLAW BOT/parser_avito")
RESULT_DIR = PARSER_DIR / "result"
RESULT_DIR.mkdir(exist_ok=True)

pending_parses = {}


def is_avito_url(url: str) -> bool:
    return "avito.ru" in url.lower() or "avito.com" in url.lower()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 *Avito Parser Bot*\n\nИспользуйте /parse", parse_mode="Markdown"
    )


async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending_parses[update.effective_user.id] = {
        "started_at": datetime.now().isoformat()
    }
    await update.message.reply_text(
        "🔗 *Avito Parser*\n\n📎 Отправьте ссылку на Avito:\n\n"
        "• https://www.avito.ru/rossiya?q=iphone\n\n⏳ Парсинг 5 страниц...",
        parse_mode="Markdown",
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()

    if user_id not in pending_parses:
        return

    if not is_avito_url(url):
        await update.message.reply_text("❌ Это не ссылка Avito", parse_mode="Markdown")
        return

    del pending_parses[user_id]

    status_msg = await update.message.reply_text(
        f"⏳ *Парсинг...*\n\n{url[:40]}...", parse_mode="Markdown"
    )

    try:
        result = await run_parser(url)

        if result["status"] == "success":
            await send_result(update, result)
        else:
            await status_msg.edit_text(
                f"⚠️ *Парсинг завершён*\n\n"
                f"Найдено: {len(result.get('listings', []))}\n"
                f"Время: {result.get('duration', 0)}сек",
                parse_mode="Markdown",
            )
            if result.get("listings"):
                await send_result(update, result)
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}", parse_mode="Markdown")


async def run_parser(url: str) -> dict:
    loop = asyncio.get_event_loop()

    def _run():
        import time
        import requests
        from bs4 import BeautifulSoup
        import openpyxl
        from urllib.parse import urlparse, parse_qs, urlencode

        result_dir = RESULT_DIR
        result_dir.mkdir(exist_ok=True)

        for f in result_dir.glob("*.xlsx"):
            try:
                f.unlink()
            except:
                pass

        start = time.time()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

        max_pages = 5
        max_items = 200
        items = []

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        for page in range(1, max_pages + 1):
            if len(items) >= max_items:
                break

            if page > 1:
                params["p"] = [str(page)]
                page_url = parsed._replace(query=urlencode(params, doseq=True)).geturl()
            else:
                page_url = url

            print(f"[Page {page}]")

            try:
                resp = requests.get(page_url, headers=headers, timeout=30)
                resp.raise_for_status()
            except Exception as e:
                print(f"[Page {page}] Error: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            page_items = 0

            for item in soup.find_all("div", attrs={"data-marker": "item"}):
                try:
                    title = item.find("a", attrs={"data-marker": "item-title"})
                    title = title.get_text(strip=True) if title else ""

                    price = item.find("span", attrs={"data-marker": "item-price"})
                    price = price.get_text(strip=True) if price else ""

                    location = item.find("div", attrs={"data-marker": "item-address"})
                    location = location.get_text(strip=True) if location else ""

                    url_el = item.find("a", href=True)
                    item_url = (
                        "https://www.avito.ru" + url_el["href"]
                        if url_el and url_el.get("href", "").startswith("/")
                        else page_url
                    )

                    if title:
                        items.append(
                            {
                                "title": title,
                                "price": price,
                                "location": location,
                                "url": item_url,
                            }
                        )
                        page_items += 1
                except:
                    pass

            if page_items == 0:
                break

            time.sleep(1)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        xlsx_path = result_dir / f"avito_{timestamp}.xlsx"

        if items:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["title", "price", "location", "url"])
            for item in items[:max_items]:
                ws.append([item["title"], item["price"], item["location"], item["url"]])
            wb.save(xlsx_path)

        return {
            "status": "success" if items else "empty",
            "listings": items[:max_items],
            "excel_path": str(xlsx_path) if items else None,
            "duration": round(time.time() - start, 1),
        }

    return await loop.run_in_executor(None, _run)


async def send_result(update: Update, result: dict):
    listings = result.get("listings", [])
    excel_path = result.get("excel_path")

    msg = f"✅ *Парсинг завершён!*\n\n📊 Объявлений: {len(listings)}\n⏱️ Время: {result.get('duration', 0)}сек"

    if excel_path and Path(excel_path).exists():
        with open(excel_path, "rb") as f:
            await update.message.reply_document(
                document=f, caption=msg, parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            msg + "\n\n⚠️ Файл не создан", parse_mode="Markdown"
        )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("parse", parse_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    print("🤖 Avito Parser Bot started")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message"])


if __name__ == "__main__":
    main()
