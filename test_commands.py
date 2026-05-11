#!/usr/bin/env python3
"""
Bot with built-in commands list
"""
import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from pathlib import Path

TOKEN = "REDACTED_TELEGRAM_BOT_TOKEN"

async def cmd_all(update, ctx):
    await update.message.reply_text("Sending /all...")

async def cmd_contacts(update, ctx):
    await update.message.reply_text("Sending /contacts...")

async def cmd_test(update, ctx):
    await update.message.reply_text("TEST OK!")

async def cmd_help(update, ctx):
    await update.message.reply_text("Commands:\n/all\n/contacts\n/test")

# Build app with context types
app = Application.builder().token(TOKEN).build()

# Add ALL handlers
app.add_handler(CommandHandler("all", cmd_all))
app.add_handler(CommandHandler("contacts", cmd_contacts))  
app.add_handler(CommandHandler("test", cmd_test))
app.add_handler(CommandHandler("help", cmd_help))

print("Bot started with /all /contacts /test /help")
print("Waiting for commands...")

# Run with drop_pending to clear any old updates
app.run_polling(drop_pending_updates=True)