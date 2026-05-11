#!/usr/bin/env python3
"""
Multi-Agent Bot Launcher
Usage: python3 run_bot.py <BOT_TOKEN>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "extensions"))

import logging
import subprocess
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from extensions.commands.start_cmd import start_cmd, DESCRIPTION as START_DESC
from extensions.commands.prian_cmd import prian_cmd, DESCRIPTION as PRIAN_DESC

logging.basicConfig(level=logging.INFO)


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
    for name, desc in [
        ("start", START_DESC),
        ("prian", PRIAN_DESC),
    ]:
        lines.append(f"/{name} — {desc}")
    lines.append("\nОтправьте URL prian.ru — бот автоматически спарсит.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_bot.py <BOT_TOKEN>")
        print("Создайте бота через @BotFather и укажите токен.")
        sys.exit(1)

    bot_token = sys.argv[1]
    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("prian", prian_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT, unknown_handler))
    print("--- MULTI-AGENT BOT ONLINE ---")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()