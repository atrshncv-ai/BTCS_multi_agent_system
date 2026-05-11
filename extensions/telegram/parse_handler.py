import os
import json
import time
import subprocess
from urllib.parse import urlparse
from avito_parser.parse_avito import parse_avito

# Simple in-memory session tracking for /parse flow
parse_sessions = {}

def is_url(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    try:
        result = urlparse(t)
        return all([result.scheme in ("http", "https"), result.netloc != ""])
    except Exception:
        return False

def handle_parse_command(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=chat_id, text="Отправьте, пожалуйста, ссылку на страницу Avito для парсинга.")
    parse_sessions[chat_id] = {"state": "AWAIT_URL"}

def handle_text_message(update, context):
    chat_id = update.effective_chat.id
    state = parse_sessions.get(chat_id, {}).get("state")
    if state != "AWAIT_URL":
        return
    url = update.message.text.strip()
    if not is_url(url):
        context.bot.send_message(chat_id=chat_id, text="Пожалуйста, отправьте корректную ссылку URL.")
        return
    context.bot.send_message(chat_id=chat_id, text="Парсинг Avito запущен. Подождите...")
    try:
        # Call the CLI entry point for avito_parser to keep separation of concerns
        avito_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "avito_parser", "parse_avito.py"))
        # Run as a subprocess and capture JSON output
        proc = subprocess.run([
            
            "python3", avito_script, "--url", url, "--max-items", "100"
        ], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            context.bot.send_message(chat_id=chat_id, text=f"Ошибка парсинга (код {proc.returncode}): {proc.stderr.strip()}")
            return
        try:
            res = json.loads(proc.stdout)
        except Exception:
            res = {"records": [], "csv_path": None}
        csv_path = res.get("csv_path")
        records = res.get("records", [])
        if csv_path and os.path.exists(csv_path):
            with open(csv_path, "rb") as f:
                context.bot.send_document(chat_id=chat_id, document=f, filename="avito_results.csv",
                                          caption=f"Парсинг завершен. Найдено позиций: {len(records)}.")
        else:
            context.bot.send_message(chat_id=chat_id, text="Парсинг выполнен, но данные не найдены на указанной странице.")
    except Exception as e:
        context.bot.send_message(chat_id=chat_id, text=f"Ошибка парсинга: {e}")
    finally:
        parse_sessions.pop(chat_id, None)
