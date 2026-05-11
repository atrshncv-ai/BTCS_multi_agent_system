#!/usr/bin/env python3
"""
MINIMAL bot - no fancy stuff, just /all and /contacts
"""
import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pathlib import Path

TOKEN = "REDACTED_TELEGRAM_BOT_TOKEN"

async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"GOT /all from {update.message.chat.id}")
    await update.message.reply_text("📊 Sending all 318K...")
    f = Path("ojp_progress/ojp_idscan_export.csv")
    if f.exists():
        with open(f, "rb") as fp:
            await update.message.reply_document(fp, "ojp_idscan_export.csv", "📊 318,954")

async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"GOT /contacts from {update.message.chat.id}")
    await update.message.reply_text("📱 Sending contacts...")
    f = Path("ojp_progress/ojp_contacts_export.csv")
    if f.exists():
        with open(f, "rb") as fp:
            await update.message.reply_document(fp, "ojp_contacts_938.csv", "📱 938")

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"GOT /test from {update.message.chat.id}")
    await update.message.reply_text("✅ OK")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"GOT TEXT: {update.message.text}")
    await update.message.reply_text(f"Got: {update.message.text}")

# Clear all other handlers first - THIS IS A NEW BOT
app = Application.builder().token(TOKEN).build()

# Add ONLY these handlers - order matters!
app.add_handler(CommandHandler("all", cmd_all))
app.add_handler(CommandHandler("contacts", cmd_contacts))
app.add_handler(CommandHandler("test", cmd_test))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("=== MINIMAL BOT STARTED ===")
print("Commands: /all /contacts /test")
app.run_polling(drop_pending_updates=True, timeout=30)