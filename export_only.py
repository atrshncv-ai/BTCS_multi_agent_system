#!/usr/bin/env python3
"""Minimal export bot - ONLY exports CSV files"""

import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from pathlib import Path

TOKEN = ""

async def export_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send all profiles CSV"""
    await update.message.reply_text("⏳ Sending all 318K profiles...")
    f = Path("ojp_progress/ojp_idscan_export.csv")
    if f.exists():
        with open(f, "rb") as fp:
            await update.message.reply_document(fp, "ojp_idscan_export.csv", "📊 All 318,954")
    else:
        await update.message.reply_text("❌ File not found")

async def export_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send contacts CSV"""
    await update.message.reply_text("⏳ Sending contacts 938...")
    f = Path("ojp_progress/ojp_contacts_export.csv")
    if f.exists():
        with open(f, "rb") as fp:
            await update.message.reply_document(fp, "ojp_contacts_938.csv", "📱 938 contacts")
    else:
        await update.message.reply_text("❌ File not found")

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot OK - /all or /contacts")

# Build app
app = Application.builder().token(TOKEN).build()

# Add handlers
app.add_handler(CommandHandler("all", export_all))
app.add_handler(CommandHandler("contacts", export_contacts))
app.add_handler(CommandHandler("test", test_cmd))

print("Starting bot: /all /contacts /test")
app.run_polling(drop_pending_updates=True)