"""
Bot error handlers and middleware.
Provides centralized error handling, logging, and user feedback.
"""

import logging
import traceback
from functools import wraps
from typing import Callable, Optional
import html

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class BotError(Exception):
    """Base exception for bot errors."""
    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or "Произошла ошибка. Попробуйте позже."


class ValidationError(BotError):
    """Validation error - user input issue."""
    pass


class ParsingError(BotError):
    """Parsing error - external service issue."""
    pass


class ExternalServiceError(BotError):
    """External service (API) error."""
    pass


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler for Telegram bot."""
    # Log full error
    update_id = update.update_id if update else "unknown"
    logger.exception(
        f"Exception while handling update {update_id}: {context.error}"
    )
    
    # Determine user-friendly message
    error_msg = _get_user_message(context.error)
    
    # Try to reply to user
    if update and update.message:
        try:
            await update.message.reply_text(
                f"❌ {error_msg}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")


def _get_user_message(error: Exception) -> str:
    """Convert exception to user-friendly message."""
    error_str = str(error)
    
    if isinstance(error, BotError):
        return error.user_message
    
    # HTTP/network errors
    if "Connection" in error_str or "timeout" in error_str.lower():
        return "Временная проблема со связью. Попробуйте через минуту."
    
    if "404" in error_str:
        return "Данные не найдены. Возможно, ссылка устарела."
    
    if "403" in error_str:
        return "Доступ запрещён. Проверьте права."
    
    # Default
    return "Произошла ошибка. Попробуйте позже или обратитесь к администратору."


def log_command(func: Callable) -> Callable:
    """Decorator to log command execution."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        cmd = update.message.text if update.message else "unknown"
        
        logger.info(
            f"Command: {cmd} | User: {user.id} ({user.username or 'no username'})"
        )
        
        try:
            return await func(update, context)
        except Exception as e:
            logger.exception(f"Command {cmd} failed: {e}")
            raise
    
    return wrapper


async def admin_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin. Return False if not authorized."""
    # TODO: Replace with actual admin check from config
    allowed_users = [123456789]  # Replace with actual user IDs
    
    if update.effective_user.id not in allowed_users:
        if update.message:
            await update.message.reply_text("⛔ Доступ запрещён.")
        return False
    return True


def escape_html(text: str) -> str:
    """Safely escape HTML entities."""
    return html.escape(str(text), quote=False)


def format_error_detail(error: Exception, max_length: int = 200) -> str:
    """Format error for display with optional detail."""
    error_str = str(error)
    if len(error_str) > max_length:
        error_str = error_str[:max_length] + "..."
    return escape_html(error_str)