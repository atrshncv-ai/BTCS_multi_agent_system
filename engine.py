import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "extensions"))

import logging
import subprocess
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from extensions.commands import all_commands

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


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
    for cmd in all_commands:
        desc = getattr(cmd, 'DESCRIPTION', getattr(cmd, '__doc__', '') or '—').strip()
        name = cmd.__name__.replace("_cmd", "").replace("_", "-")
        lines.append(f"/{name} — {desc}")
    lines.append("\nОтправьте URL prian.ru — бот автоматически спарсит.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def main():
    # TOKEN = здесь будет реальный токен при запуске
    raise RuntimeError("Укажите BOT_TOKEN = 'ваш_токен' перед запуском")


if __name__ == "__main__":
    main()