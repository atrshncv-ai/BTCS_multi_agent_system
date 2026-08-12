#!/usr/bin/env python3
"""Simple debug bot with print statements"""

import asyncio
import logging
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

TOKEN = ""

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"RECEIVED /start from {update.effective_user.id}")
    await update.message.reply_text("👋 Hi! Use /all for all profiles, /contacts for contacts")

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"RECEIVED /test from {update.effective_user.id}")
    await update.message.reply_text("✅ Works!")

async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"RECEIVED /all from {update.effective_user.id}")
    from pathlib import Path
    csv_file = Path("ojp_progress/ojp_idscan_export.csv")
    if csv_file.exists():
        with open(csv_file, "rb") as f:
            await update.message.reply_document(document=f, filename="ojp_idscan_export.csv", caption="📊 All: 318,954")
    else:
        await update.message.reply_text("❌ File not found")

async def cmd_cont(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"RECEIVED /contacts from {update.effective_user.id}")
    from pathlib import Path
    csv_file = Path("ojp_progress/ojp_contacts_export.csv")
    if csv_file.exists():
        with open(csv_file, "rb") as f:
            await update.message.reply_document(document=f, filename="ojp_contacts_938.csv", caption="📱 Contacts: 938")
    else:
        await update.message.reply_text("❌ File not found")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"RECEIVED /help from {update.effective_user.id}")
    await update.message.reply_text("Commands:\n/all - 318K profiles\n/contacts - 938 contacts\n/test - test")

def main():
    print("=== Starting debug bot ===")
    app = Application.builder().token(TOKEN).build()
    
    print("Adding handlers...")
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("contacts", cmd_cont))
    app.add_handler(CommandHandler("help", cmd_help))
    
    print("=== Bot ready, starting polling ===")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()