import logging, subprocess, env
from telegram.ext import Application, MessageHandler, filters

logging.basicConfig(level=logging.INFO)

async def h(u, c):
    text = u.message.text
    await u.message.reply_text("🚀 Gemma 26B: Начинаю глубокий анализ...")
    try:
        res = subprocess.run(["/opt/homebrew/bin/python3.10", "/Users/aiserver/.openclaw/workspace/scripts/multi_brain.py", text], capture_output=True, text=True, timeout=600)
        await u.message.reply_text(res.stdout[:4000] if res.stdout else "Анализ завершен.")
    except Exception as e:
        await u.message.reply_text(f"Ошибка: {str(e)}")

if __name__ == "__main__":
    app = Application.builder().token(env.TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, h))
    print("--- ENGINE ONLINE (HIDDEN) ---")
    app.run_polling(drop_pending_updates=True)