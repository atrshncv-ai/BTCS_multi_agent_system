#!/usr/bin/env python3
"""Webhook-based bot - no polling"""

import json
import logging
from pathlib import Path
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = "REDACTED_TELEGRAM_BOT_TOKEN"

async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = Path("ojp_progress/ojp_idscan_export.csv")
    with open(f, "rb") as fp:
        await update.message.reply_document(fp, "ojp_idscan_export.csv", "📊 318,954")

async def handle_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = Path("ojp_progress/ojp_contacts_export.csv")
    with open(f, "rb") as fp:
        await update.message.reply_document(fp, "ojp_contacts_938.csv", "📱 938")

async def handle_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Works")

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/all /contacts /test")

async def post_init(app):
    app.bot["my_commands"] = [
        ("all", "Export all profiles"),
        ("contacts", "Export contacts"),
        ("test", "Test"),
    ]

# Build with webhook
app = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

app.add_handler(CommandHandler("all", handle_all))
app.add_handler(CommandHandler("contacts", handle_contacts))
app.add_handler(CommandHandler("test", handle_test))
app.add_handler(CommandHandler("help", handle_help))

# Use webhook mode
print("=== Starting webhook bot ===")
app.run_webhook(
    listen="0.0.0.0",
    port=8443,
    url_path="webhook",
    secret_token="SECRET123",
    drop_pending_updates=True,
)