#!/usr/bin/env python3
"""Simple bot to export OJP results"""

import asyncio
import json
import csv
from pathlib import Path
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "REDACTED_TELEGRAM_BOT_TOKEN"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Use /export for all profiles, /contacts for contacts with emails/phones")

async def export_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Sending all profiles (318K)...")
    csv_file = Path("ojp_progress/ojp_idscan_export.csv")
    if csv_file.exists():
        with open(csv_file, "rb") as f:
            await update.message.reply_document(document=f, filename="ojp_idscan_export.csv", caption="📊 All profiles: 318,954")
    else:
        await update.message.reply_text("❌ File not found")

async def export_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Sending contacts (938)...")
    csv_file = Path("ojp_progress/ojp_contacts_export.csv")
    if csv_file.exists():
        with open(csv_file, "rb") as f:
            await update.message.reply_document(document=f, filename="ojp_contacts_938.csv", caption="📱 Contacts: 938")
    else:
        await update.message.reply_text("❌ File not found")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_all))
    app.add_handler(CommandHandler("contacts", export_contacts))
    app.add_handler(CommandHandler("test", lambda u, c: u.message.reply_text("✅ Works!")))
    
    print("Starting simple bot...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()