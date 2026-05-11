#!/usr/bin/env python3
"""
Simple export bot that just sends the CSV files.
Run this INSTEAD of parse_bot_v6.py
"""

import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from pathlib import Path
import os

TOKEN = "REDACTED_TELEGRAM_BOT_TOKEN"

async def send_csv_file(update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str, caption: str):
    """Send a CSV file"""
    filepath = Path(f"ojp_progress/{filename}")
    if not filepath.exists():
        await update.message.reply_text(f"❌ File not found: {filename}")
        return
    
    try:
        with open(filepath, "rb") as f:
            await update.message.reply_document(
                document=f, 
                filename=filename,
                caption=caption
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send all profiles"""
    await send_csv_file(update, context, "ojp_idscan_export.csv", "📊 All profiles: 318,954")

async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send contacts"""
    await send_csv_file(update, context, "ojp_contacts_export.csv", "📱 Contacts: 938")

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test command"""
    await update.message.reply_text("✅ Bot works!")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Status"""
    await update.message.reply_text("🤖 Bot is running. Use /all or /contacts")

def main():
    print("Starting simple export bot...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("status", cmd_status))
    
    print("Commands: /all /contacts /test /status")
    app.run_polling(drop_pending_updates=True, timeout=60)

if __name__ == "__main__":
    main()