#!/bin/bash
# Запуск multi-agent бота
# usage: ./run_engine.sh <BOT_TOKEN>

BOT_TOKEN="${1}"
if [ -z "$BOT_TOKEN" ]; then
    echo "Usage: $0 <BOT_TOKEN>"
    exit 1
fi

cd /Users/aiserver/OPENCLAW\ BOT

python3 <<EOF
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "extensions"))

import logging
import subprocess
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from extensions.commands import all_commands
from extensions.commands.start_cmd import start_cmd
from extensions.commands.prian_cmd import prian_cmd

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "$BOT_TOKEN"

async def unknown_handler(update, context):
    text = update.message.text.strip()
    await update.message.reply_text("🚀 Gemma 26B: Начинаю глубокий анализ...")
    try:
        res = subprocess.run(
            ["/opt/homebrew/bin/python3.10",
             "/Users/aiserver/.openclaw/workspace/scripts/multi_brain.py",
             text],
            capture_output=True, text=True, timeout=600
        )
        await update.message.reply_text(
            res.stdout[:4000] if res.stdout else "Анализ завершён."
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

async def help_cmd(update, context):
    lines = ["🤖 <b>Команды Multi-Agent Bot</b>\n"]
    for cmd_info in all_commands:
        name = cmd_info["name"]
        desc = cmd_info.get("description", "—")
        lines.append(f"/{name} — {desc}")
    lines.append("\nОтправьте URL prian.ru — бот автоматически спарсит.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("prian", prian_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT, unknown_handler))
    print("--- MULTI-AGENT BOT ONLINE ---")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
EOF