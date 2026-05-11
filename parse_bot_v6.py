#!/usr/bin/env python3
"""
OpenClaw Telegram Bot v8
Unified parser bot with stable architecture.
"""

import asyncio
import csv
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Add project root and extensions to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "extensions"))

# Load environment variables from .env
for env_file in [Path(__file__).parent / ".env", Path(__file__).parent / ".env.chatwoot"]:
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

import os

# Import new modules
from config import get_global_config, ParserConfig
from context import get_context
from middleware import error_handler, log_command
from outreach.outreach_agent import OutreachAgent
from whatsapp_client import get_wa_client, WhatsAppClient

try:
    from agents import AgentOrchestrator, AgentContext, get_supervisor
    MULTI_AGENT_AVAILABLE = True
except ImportError as e:
    MULTI_AGENT_AVAILABLE = False
    logger.warning(f"Multi-agent system not available: {e}")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Load config
config = get_global_config()
bot_ctx = get_context()

# Initialize components
RESULT_DIR = config.parser.avito_result_dir
RESULT_DIR.mkdir(exist_ok=True)

OJP_PROGRESS_DIR = config.parser.ojp_progress_dir
OJP_API_URL = config.parser.ojp_api_url

agent: Optional[OutreachAgent] = None

CATALOG_HEADER = {
    "Название": "company_name",
    "Ссылка": "company_url",
    "ID": "company_id",
    "Объекты": "total_objects",
}

ENRICH_HEADER = {
    "Название": "company_name",
    "Страна": "countries",
    "Объекты": "total_objects",
    "Менеджер": "manager_name",
    "Должность": "manager_position",
    "Языки": "manager_languages",
    "Телефоны": "phones",
    "Email": "emails",
    "WhatsApp": "whatsapp",
    "Telegram": "telegram",
    "Ссылка": "company_url",
}

PRIAN_HEADER = {
    "Название": "title",
    "Цена": "price",
    "Локация": "location",
    "Площадь": "area",
    "Спальни": "bedrooms",
    "Ванные": "bathrooms",
    "Ссылка": "url",
    "Тип": "listing_type",
    "Компания": "company_name",
    "Агент": "agent_name",
    "Должность агента": "agent_position",
    "Телефон": "phone",
    "Email": "email",
    "WhatsApp": "whatsapp",
    "Telegram": "telegram",
}

OJP_JOB_HEADER = {
    "Должность": "title",
    "Тип": "job_type",
    "Зарплата": "salary",
    "ID вакансии": "job_id",
    "Ссылка": "url",
    "Описание": "description",
    "Навыки": "skills",
    "Дата": "posted_date",
}

OJP_PROFILE_HEADER = {
    "ID профиля": "profile_id",
    "Имя": "name",
    "Специализация": "title",
    "Почасовая ставка": "hourly_rate",
    "ID Proof": "id_proof_score",
    "Категория": "category",
    "Ссылка": "url",
}


def _init_agent() -> OutreachAgent:
    """Lazy initialization of OutreachAgent with config."""
    return OutreachAgent(
        cw_url=config.chatwoot.url,
        cw_token=config.chatwoot.token,
        cw_account_id=config.chatwoot.account_id,
        cw_inbox_id=config.chatwoot.whatsapp_inbox,
    )


def is_avito_url(url):
    return "avito.ru" in url.lower()

def is_prian_url(url):
    return "prian.ru" in url.lower()

def is_company_url(url):
    return "prian.ru" in url.lower() and "/company/" in url

def is_company_catalog_url(url):
    return "prian.ru" in url.lower() and "/company/" in url and ".html" not in url


def make_xlsx(rows, header_map):
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"

    header_font = Font(name="Arial", bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_align = Alignment(vertical="top", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="D9E2F3"),
        right=Side(style="thin", color="D9E2F3"),
        top=Side(style="thin", color="D9E2F3"),
        bottom=Side(style="thin", color="D9E2F3"),
    )

    headers = list(header_map.keys())
    for col_idx, ru_name in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=ru_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    for row_idx, row in enumerate(rows, 2):
        for col_idx, ru_name in enumerate(headers, 1):
            en_key = header_map[ru_name]
            v = row.get(en_key, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            if isinstance(v, dict):
                v = ", ".join(f"{k}: {val}" for k, val in v.items()) if v else ""
            v = str(v) if v else ""
            cell = ws.cell(row=row_idx, column=col_idx, value=v)
            cell.alignment = cell_align
            cell.border = thin_border

    col_widths = {
        "Название": 30, "Ссылка": 45, "ID": 15, "Объекты": 12,
        "Страна": 15, "Менеджер": 25, "Должность": 20,
        "Языки": 25, "Телефоны": 25, "Email": 25,
        "WhatsApp": 30, "Telegram": 25,
        "Цена": 15, "Локация": 25, "Площадь": 12, "Спальни": 10,
        "Ванные": 10, "Тип": 12, "Компания": 25,
        "Агент": 20, "Телефон": 20,
        "Описание": 40, "Зарплата": 15, "Дата": 15,
        "Должность агента": 20, "ID вакансии": 15,
        "Навыки": 30, "ID профиля": 15, "Имя": 20,
        "Специализация": 30, "Почасовая ставка": 15,
        "ID Proof": 12, "Категория": 18,
    }
    for col_idx, ru_name in enumerate(headers, 1):
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        width = col_widths.get(ru_name, 18)
        ws.column_dimensions[col_letter].width = width

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_csv(rows, header_map):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(header_map.keys()))
    writer.writeheader()
    for row in rows:
        csv_row = {}
        for ru_name, en_key in header_map.items():
            v = row.get(en_key, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            if isinstance(v, dict):
                v = ", ".join(f"{k}: {val}" for k, val in v.items()) if v else ""
            csv_row[ru_name] = str(v) if v else ""
        writer.writerow(csv_row)
    return output.getvalue().encode("utf-8-sig")


async def send_csv(update, data, filename, caption):
    try:
        # Try to read pre-made CSV first
        csv_path = Path(f"ojp_progress/{filename.replace('.xlsx', '.csv')}")
        if csv_path.exists():
            with open(csv_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename.replace('.xlsx', '.csv'), caption=caption)
            return
        
        # Otherwise create xlsx
        xlsx_bytes = make_xlsx(data["rows"], data["header"])
        ext = ".xlsx"
        
        path = tempfile.mktemp(suffix=ext)
        try:
            with open(path, "wb") as f:
                f.write(xlsx_bytes)
            with open(path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename, caption=caption)
        finally:
            os.remove(path)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def start_command(update, context):
    cw_status = "✅ подключён" if agent and agent.chatwoot_configured else "❌ не настроен"
    await update.message.reply_text(
        "<b>🤖 OpenClaw Bot v8</b>\n\n"
        "📦 <b>ПАРСИНГ:</b>\n"
        "🔗 /parse — Avito (отправь ссылку)\n"
        "🏠 /prian — Prian.ru (отправь ссылку)\n"
        "🏢 /company — компания Prian (отправь ссылку)\n"
        "📋 /catalog — каталог компаний\n"
        "☎️ /enrich — все компании с контактами\n\n"
        "🇵🇭 <b>ONLINEJOBS.PH:</b>\n"
        "🔍 /ojp_scan — сканирование профилей\n"
        "📊 /ojp_progress — прогресс сканирования\n"
        "📥 /ojp_export — экспорт активных профилей\n"
        "⚡ /ojp_test — тест 1000 карточек\n"
        "📱 /contacts — экспорт контактов\n\n"
        "💬 <b>OUTREACH (Chatwoot):</b>\n"
        f"Статус: {cw_status}\n"
        "📤 /outreach — загрузить контакты\n"
        "💬 /send — отправить сообщение\n"
        "📋 /conversations — диалоги\n\n"
        "🤖 <b>MULTI-AGENT:</b>\n"
        "/ai <запрос> — умная маршрутизация через LLM\n\n"
        "ℹ️ Отправь ссылку — бот определит тип автоматически"
    , parse_mode="HTML")


async def ai_command(update, context):
    """Multi-agent command — routes user request via LLM to the best agent(s)."""
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна. Проверьте установку.")
        return

    user_text = " ".join(context.args).strip() if context.args else ""
    if not user_text:
        await update.message.reply_text(
            "🤖 Multi-Agent Router\n\n"
            "Отправьте запрос:\n"
            "/ai парсить prian.ru/company/turkey.html\n"
            "/ai найти виртуальных ассистентов\n"
            "/ai загрузить контакты и отправить сообщение\n\n"
            "Просто опишите задачу — система выберет нужного агента.",
        )
        return

    status_msg = await update.message.reply_text(
        f"🤖 Multi-Agent\n"
        f"{user_text[:80]}{'...' if len(user_text) > 80 else ''}\n\n"
        f"⏳ Анализирую..."
    )

    _status_lock = False
    _last_send = 0.0

    async def on_status(text: str):
        nonlocal _status_lock, _last_send
        if _status_lock:
            return
        import time as _time
        now = _time.time()
        if now - _last_send < 1.2:
            return
        try:
            _status_lock = True
            _last_send = now
            await status_msg.edit_text(text)
        except Exception:
            pass
        finally:
            _status_lock = False

    try:
        session_key = f"telegram_{update.effective_user.id}"
        ctx = AgentContext(
            session_id=str(update.effective_chat.id),
            user_id=update.effective_user.id,
            session_key=session_key,
        )
        ctx.ensure_session()

        await ctx.add_turn("system", f"Новая сессия: {user_text[:200]}", "system")

        orchestrator = AgentOrchestrator(
            user_id=update.effective_user.id,
            session_key=session_key,
        )
        orchestrator.session_id = str(update.effective_chat.id)
        orchestrator.set_status_callback(on_status)

        result = await orchestrator.process(user_text, ctx)

        response = result.get("response", "Нет ответа")
        plan = result.get("plan")
        errors = result.get("errors", [])
        duration = result.get("duration", 0)

        lines = [response]

        if plan:
            agents_used = ", ".join(plan["agents"])
            lines.append(f"\n📋 Агенты: {agents_used}")

        if errors:
            lines.append(f"\n⚠️ {'; '.join(errors[:2])}")

        lines.append(f"\n⏱ {duration:.1f}с")

        full_response = "\n".join(lines)
        if len(full_response) > 4000:
            full_response = full_response[:4000] + "\n\n...(обрезано)"

        await status_msg.edit_text(full_response)
        await ctx.add_turn("assistant", full_response, "orchestrator")

        agent_results = result.get("agent_results", [])
        for r in agent_results:
            if r.get("status") == "success" and r.get("data"):
                data = r["data"]
                if isinstance(data, dict):
                    if data.get("records") and len(data["records"]) > 0:
                        records = data["records"]
                        if isinstance(records, list) and len(records) > 0:
                            first = records[0]
                            if isinstance(first, dict):
                                await update.message.reply_text(
                                    f"📊 Пример результата:\n"
                                    f"  {json.dumps(first, ensure_ascii=False)[:300]}"
                                )
                                break

        await orchestrator.close()
        await ctx.close()

    except Exception as e:
        logger.exception(f"ai_command error: {e}")
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")
        except Exception:
            await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ai_history_command(update, context):
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна.")
        return

    try:
        ctx = AgentContext(
            session_id=str(update.effective_chat.id),
            user_id=update.effective_user.id,
            session_key=f"telegram_{update.effective_user.id}",
        )
        ctx.ensure_session()

        import asyncio
        turns_data = await ctx.get_conversation(20)
        await ctx.close()

        if not turns_data:
            await update.message.reply_text("📭 История пуста — начните с /ai")
            return

        lines = ["📜 <b>История разговора</b>\n"]
        for i, t in enumerate(turns_data):
            role = t.agent_name or t.role
            content = t.content[:200]
            lines.append(f"<b>{role}</b>: {content}")
            if i > 14:
                lines.append(f"... и ещё {len(turns_data) - 15} сообщений")
                break

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception(f"ai_history error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ai_stats_command(update, context):
    """Show per-agent performance statistics."""
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна.")
        return

    try:
        supervisor = get_supervisor()
        health = supervisor.get_agent_health()
        summary = supervisor.get_status_summary()
        recent = supervisor.get_recent_executions(limit=10)

        lines = [
            "📊 <b>Agent Performance Stats</b>\n",
            f"Всего запусков: {summary.get('hour_executions', 0)} за час, "
            f"{summary.get('day_executions', 0)} за день\n",
        ]

        if not health:
            lines.append("Нет данных — запустите /ai команду")
        else:
            lines.append("<b>Агенты:</b>")
            for h in health:
                name = h.get("agent_name", "?")
                total = h.get("total_executions", 0)
                success = h.get("total_success", 0)
                failures = h.get("consecutive_failures", 0)
                avg_d = round(h.get("avg_duration", 0), 1)
                rate = round(success / total * 100) if total > 0 else 0

                bar = "🟩" * (rate // 25) + "🟧" * ((rate % 25) // 10)
                icon = "✅" if failures == 0 else ("⚠️" if failures < 3 else "❌")
                lines.append(
                    f"{icon} <b>{name}</b>\n"
                    f"   {total} запусков, {rate}% успех {bar}\n"
                    f"   ср. время: {avg_d}с, consecutive failures: {failures}"
                )

        if recent:
            lines.append("\n<b>Последние запуски:</b>")
            for r in recent[:5]:
                icon = "✅" if r.get("status") == "success" else "❌"
                ts = str(r.get("created_at", ""))[:16]
                dur = round(r.get("duration_seconds", 0), 1)
                err = (r.get("error") or "")[:40]
                lines.append(
                    f"{icon} {r.get('agent_name', '?')} | {dur}с | {ts} | {err}"
                )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception(f"ai_stats error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ai_analytics_command(update, context):
    """Show TZ analytics: sellers, conversations, products, funnel."""
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна.")
        return

    try:
        from agents.tz_database import TZDatabase
        db = TZDatabase()
        summary = db.get_analytics_summary()

        lines = [
            "📊 <b>TZ Аналитика</b>\n",
            f"<b>Поставщики:</b>",
            f"  Всего: {summary.get('total_sellers', 0)}",
            f"  Новых: {summary.get('new_sellers', 0)} | "
            f"Квалифицированных: {summary.get('qualified_sellers', 0)}\n",
            f"<b>Диалоги:</b>",
            f"  Активных: {summary.get('active_conversations', 0)}",
            f"  На проверке: {summary.get('requires_review', 0)}\n",
            f"<b>Сообщения:</b>",
            f"  Всего: {summary.get('total_messages', 0)}",
            f"  AI-сгенерированных: {summary.get('ai_generated_messages', 0)}\n",
            f"<b>Документы:</b>",
            f"  Получено: {summary.get('documents_received', 0)}",
            f"  Обработано: {summary.get('documents_parsed', 0)}\n",
            f"<b>Товары:</b>",
            f"  Извлечено продуктов: {summary.get('products_extracted', 0)}",
            f"  Средний relevance score: {summary.get('avg_relevance_score', 0)}",
        ]

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception(f"ai_analytics error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ai_approvals_command(update, context):
    """Show messages pending operator approval."""
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна.")
        return

    try:
        from agents.tz_database import TZDatabase
        db = TZDatabase()
        pending = db.get_pending_approvals(limit=10)

        if not pending:
            await update.message.reply_text("✅ Нет сообщений на проверке.")
            return

        lines = ["📋 <b>Сообщения на проверке</b>\n"]
        for m in pending:
            seller = m.get("seller_name", "неизвестно")
            channel = m.get("channel", "?")
            stage = m.get("current_stage", "?")
            text = (m.get("text") or "")[:120]
            msg_id = str(m.get("id", ""))[:8]
            lines.append(
                f"<b>{seller}</b> [{channel}]\n"
                f"  step: {stage}\n"
                f"  {text}...\n"
                f"  /ai_approve {msg_id} | /ai_reject {msg_id}\n"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception(f"ai_approvals error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ai_import_command(update, context):
    """Import sellers from CSV/XLSX via /ai_import."""
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "📤 <b>Импорт поставщиков</b>\n\n"
            "Отправьте файл CSV/XLSX напрямую боту,\n"
            "или укажите путь: /ai_import /path/to/file.csv\n\n"
            "Ожидаемые колонки: seller_name, source_platform, source_url, region, category",
            parse_mode="HTML",
        )
        return

    file_path = " ".join(args)
    await update.message.reply_text(f"⏳ Загружаю: {file_path}")

    try:
        from agents import AgentContext, AgentOrchestrator, get_supervisor
        ctx = AgentContext(
            session_id=str(update.effective_chat.id),
            user_id=update.effective_user.id,
            session_key=f"telegram_{update.effective_user.id}",
        )
        ctx.ensure_session()

        orch = AgentOrchestrator(
            user_id=update.effective_user.id,
            session_key=f"telegram_{update.effective_user.id}",
        )
        orch.session_id = str(update.effective_chat.id)

        result = await orch.process(
            f"import {file_path}",
            ctx,
        )

        response = result.get("response", "")
        await update.message.reply_text(f"✅ {response}\n⏱ {result.get('duration', 0):.1f}с")

    except Exception as e:
        logger.exception(f"ai_import error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ai_status_command(update, context):
    """Show multi-agent system health: agent stats, failures, alerts."""
    if not MULTI_AGENT_AVAILABLE:
        await update.message.reply_text("❌ Multi-agent система не доступна.")
        return

    try:
        supervisor = get_supervisor()
        summary = supervisor.get_status_summary()
        health = supervisor.get_agent_health()
        alerts = supervisor.get_alerts(acknowledged=False, limit=5)

        lines = [
            "🏥 <b>Agent System Health</b>\n",
            f"⏱ Час: {summary.get('hour_executions', 0)} запусков (ср. {summary.get('hour_avg_duration', 0)}с)",
            f"📅 День: {summary.get('day_executions', 0)} запусков",
            f"✅ Здоровых: {summary.get('agents_healthy', 0)} | "
            f"⚠️ Деградировавших: {summary.get('agents_degraded', 0)} | "
            f"❌ Проблемных: {summary.get('agents_failing', 0)}\n",
        ]

        if alerts:
            lines.append("🚨 <b>Активные алерты:</b>")
            for a in alerts[:3]:
                icon = "🔴" if a.get("alert_type") == "critical" else "🟡"
                lines.append(f"{icon} {a.get('agent_name')}: {a.get('message', '')[:80]}")
            lines.append("")

        if health:
            lines.append("<b>Агенты:</b>")
            for h in health:
                name = h.get("agent_name", "?")
                failures = h.get("consecutive_failures", 0)
                total = h.get("total_executions", 0)
                success = h.get("total_success", 0)
                rate = round(success / total * 100) if total > 0 else 0
                avg_d = round(h.get("avg_duration", 0), 1)
                last_s = h.get("last_success")
                last_s_str = str(last_s)[:16] if last_s else "никогда"

                if failures >= 3:
                    icon = "❌"
                elif failures > 0:
                    icon = "⚠️"
                else:
                    icon = "✅"

                lines.append(
                    f"{icon} {name}: {total} запусков, "
                    f"{rate}% успех, ср. {avg_d}с, последний успех: {last_s_str}"
                )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception(f"ai_status error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def parse_command(update, context):
    await bot_ctx.set_pending(update.effective_user.id, "parse")
    await update.message.reply_text("🔗 Отправьте ссылку на Avito")


async def prian_command(update, context):
    await bot_ctx.set_pending(update.effective_user.id, "prian")
    await update.message.reply_text("🏠 Отправьте ссылку на prian.ru")


async def ojp_command(update, context):
    args = context.args or []
    logger.info(f"OJP command received: args={args}")
    mode = "jobs"
    keyword = ""
    max_pages = 10

    if not args:
        await update.message.reply_text(
            "🇵🇭 OnlineJobs.ph\n\n"
            "Поиск вакансий:\n"
            "/ojp_seo — вакансии SEO\n"
            "/ojp_va — виртуальные ассистенты\n"
            "/ojp_design — дизайнеры\n"
            "/ojp_marketing — маркетинг\n"
            "/ojp_dev — разработчики\n"
            "/ojp_all — все вакансии (~300)\n\n"
            "Кандидаты:\n"
            "/ojp_profiles — все кандидаты (31 категория)\n\n"
            "Или наберите:\n"
            "/ojp <ключевое слово>"
        )
        return

    if args[0] in ("all-jobs", "all_jobs", "all", "все"):
        mode = "all-jobs"
        keyword = " ".join(args[1:]) if len(args) > 1 else ""
        max_pages = 50
    elif args[0] in ("all-profiles", "all_profiles", "profiles", "кандидаты"):
        mode = "all-profiles"
        max_pages = 50
    elif args[0] in ("detail",):
        if len(args) < 2:
            await update.message.reply_text("❌ Укажите URL: /ojp detail <url>")
            return
        mode = "detail"
        keyword = args[1]
    else:
        mode = "jobs"
        keyword = " ".join(args)
        max_pages = 10

    status = await update.message.reply_text(f"⏳ Парсинг OnlineJobs.ph ({mode}: {keyword or 'все'})...")
    try:
        import httpx
        timeout = 1800 if mode == "all-profiles" else 600 if mode == "all-jobs" else 300
        payload = {"mode": mode, "keyword": keyword, "max_pages": max_pages, "category": keyword or "virtual-assistant"}
        if mode == "detail":
            payload = {"mode": "detail", "url": keyword}
        logger.info(f"OJP API request: {payload}")
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post("http://127.0.0.1:8001/parse/ojp", json=payload)
            data = resp.json()
        logger.info(f"OJP API response: ok={data.get('ok')}, count={data.get('count', len(data.get('results', [])))}")

        results = data.get("results", [])
        if not results:
            err = data.get("error", "")
            logger.warning(f"OJP no results: error={err}")
            await status.edit_text(f"❌ Ничего не найдено{f': {err[:100]}' if err else ''}")
            return

        header = OJP_JOB_HEADER if results and "job_id" in results[0] else OJP_PROFILE_HEADER
        await send_csv(
            update,
            {"rows": results, "header": header},
            f"ojp_{mode}_{len(results)}.csv",
            f"🇵🇭 Результатов: {len(results)}",
        )
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


OJP_SHORTCUTS = {
    "ojp_va": ("jobs", "virtual assistant", 10),
    "ojp_seo": ("jobs", "seo", 10),
    "ojp_design": ("jobs", "designer", 10),
    "ojp_marketing": ("jobs", "marketing", 10),
    "ojp_dev": ("jobs", "developer", 10),
    "ojp_accounting": ("jobs", "accounting", 10),
    "ojp_all": ("all-jobs", "", 50),
    "ojp_profiles": ("all-profiles", "", 10),
}


async def ojp_shortcut(update, context):
    cmd = update.message.text.split()[0].lstrip("/")
    if cmd not in OJP_SHORTCUTS:
        await ojp_command(update, context)
        return
    mode, keyword, max_pages = OJP_SHORTCUTS[cmd]
    context.args = [keyword] if keyword else (["all"] if mode == "all-jobs" else ["profiles"])
    logger.info(f"OJP shortcut: cmd={cmd}, mode={mode}, keyword={keyword}, pages={max_pages}")
    status = await update.message.reply_text(f"⏳ Парсинг OnlineJobs.ph ({mode}: {keyword or 'все'})...")
    try:
        import httpx
        timeout = 1800 if mode == "all-profiles" else 600 if mode == "all-jobs" else 300
        payload = {"mode": mode, "keyword": keyword, "max_pages": max_pages, "category": keyword or "virtual-assistant"}
        logger.info(f"OJP API request: {payload}")
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post("http://127.0.0.1:8001/parse/ojp", json=payload)
            data = resp.json()
        logger.info(f"OJP API response: ok={data.get('ok')}, count={data.get('count', len(data.get('results', [])))}")
        results = data.get("results", [])
        if not results:
            err = data.get("error", "")
            await status.edit_text(f"❌ Ничего не найдено{f': {err[:100]}' if err else ''}")
            return
        header = OJP_JOB_HEADER if results and "job_id" in results[0] else OJP_PROFILE_HEADER
        await send_csv(
            update,
            {"rows": results, "header": header},
            f"ojp_{mode}_{len(results)}.xlsx",
            f"🇵🇭 Результатов: {len(results)}",
        )
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


OJP_SCAN_HEADER = {
    "ID профиля": "profile_id",
    "Имя": "name",
    "Категория": "category",
    "Почасовая ставка": "hourly_rate",
    "ID Proof": "id_proof_score",
    "Топ-навыки": "skills_top",
    "Другие навыки": "skills_other",
    "Обзор": "overview",
    "Описание": "description",
    "Доступность": "availability",
    "Последний вход": "last_active",
    "Ссылка": "url",
}


async def ojp_scan_start(update, context):
    args = context.args or []
    cmd = update.message.text.lstrip('/').split()[0]
    
    if cmd == "ojp_full":
        max_profiles = 600000
        count_type = "600K"
    else:
        max_profiles = int(args[0]) if args and args[0].isdigit() else 100000
        count_type = "100K"
    
    status = await update.message.reply_text(f"⏳ Запуск сканирования {count_type} OnlineJobs.ph...\n\n1/2: Загрузка карты сайта...")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post("http://127.0.0.1:8001/parse/ojp_scan", json={"action": "phase1sitemap"})
            data = resp.json()
        if not data.get("ok"):
            await status.edit_text(f"❌ Ошибка Phase 1: {data.get('error', '?')[:200]}")
            return
        total_ids = data.get("total_ids", 0)
        await status.edit_text(
            f"✅ Найдено {total_ids:,} профилей в картах сайта\n\n"
            f"2/2: Начинаю загрузку деталей ({count_type})...\n"
            f"📊 /ojp_progress — проверка прогресса\n"
            f"📥 /ojp_export — экспорт"
        )
        import threading
        def _run_scan():
            import subprocess
            cmd = ["/opt/homebrew/bin/python3.10", str(Path(__file__).parent / "extensions" / "ojp_parser" / "scan_profiles.py"), "--mode", "phase2"]
            if max_profiles > 0:
                cmd += ["--max-profiles", str(max_profiles)]
            subprocess.run(cmd, capture_output=True, text=True, timeout=86400)
        scan_thread = threading.Thread(target=_run_scan, daemon=True)
        scan_thread.start()
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


async def ojp_progress(update, context):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("http://127.0.0.1:8001/ojp_scan_progress")
            data = resp.json()
        if not data.get("ok"):
            await update.message.reply_text("❌ Сканирование не запущено. Используйте /ojp_scan")
            return
        st = data.get("status", "?")
        total = data.get("total_ids", 0)
        processed = data.get("processed", 0)
        errors = data.get("errors", 0)
        pct = data.get("progress_pct", 0)
        active = data.get("active_profiles", 0)
        started = data.get("started_at", "?")[:19]
        updated = data.get("last_updated", "?")[:19]
        completed = data.get("completed_at", "")
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        status_icon = "✅" if st == "completed" else "⏳"
        text = (
            f"{status_icon} <b>Прогресс сканирования</b>\n\n"
            f"Всего ID: {total:,}\n"
            f"Обработано: {processed:,} ({pct}%)\n"
            f"Активных: {active:,}\n"
            f"Ошибок (404): {errors:,}\n\n"
            f"[{bar}] {pct}%\n\n"
            f"Начато: {started}\n"
            f"Обновлено: {updated}"
        )
        if completed:
            text += f"\nЗавершено: {completed[:19]}"
            text += f"\n\n📥 /ojp_export — скачать результат"
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def ojp_export(update, context):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("http://127.0.0.1:8001/ojp_scan_progress")
            data = resp.json()
        active = data.get("active_profiles", 0)
        processed = data.get("processed", 0)
        if processed == 0:
            await update.message.reply_text("❌ Нет данных. Сначала запустите /ojp_scan")
            return
        progress_file = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress/profiles.json")
        if not progress_file.exists():
            await update.message.reply_text("❌ Файл результатов не найден")
            return
        results = json.loads(progress_file.read_text())
        active_results = [r for r in results if r.get("is_active")]
        if not active_results:
            await update.message.reply_text("❌ Активные профили не найдены")
            return
        await send_csv(
            update,
            {"rows": active_results, "header": OJP_SCAN_HEADER},
            f"ojp_all_profiles_{len(active_results)}.xlsx",
            f"🇵🇭 Экспортировано: {len(active_results)} активных профилей из {processed} обработанных",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


OJP_TEST_HEADER = {
    "ID профиля": "profile_id",
    "Имя": "name",
    "Специализация": "title",
    "Почасовая ставка": "hourly_rate",
    "ID Proof": "id_proof_score",
    "Образование": "education",
    "Последний вход": "last_active",
    "Описание": "description",
    "Top навыки": "skills_top",
    "Доступность": "availability",
    "Ссылка": "url",
}


async def ojp_test_command(update, context):
    args = context.args or []
    count = int(args[0]) if args and args[0].isdigit() else 1000
    status = await update.message.reply_text(f"⏳ Парсинг {count} карточек с skillsearch...\nЭто займёт ~2 минуты")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"http://127.0.0.1:8001/parse/ojp_test?max_profiles={count}"
            )
            data = resp.json()
        results = data.get("results", [])
        if not results:
            await status.edit_text(f"❌ Ничего не найдено")
            return
        await send_csv(
            update,
            {"rows": results, "header": OJP_TEST_HEADER},
            f"ojp_test_{len(results)}.xlsx",
            f"🧪 Тест: {len(results)} карточек",
        )
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


ID_SCAN_HEADER = {
    "ID": "profile_id",
    "Ссылка": "profile_url",
    "Статус": "status",
    "Имя": "name",
    "Специализация": "title",
    "Почасовая ставка": "hourly_rate",
    "ID Proof": "id_proof_score",
    "Образование": "education",
    "Последний вход": "last_active",
    "Top навыки": "skills_top",
    "Описание": "description",
    "Email": "email",
    "Телефон": "phone",
    "Telegram": "telegram",
    "WhatsApp": "whatsapp",
    "Facebook": "facebook",
    "LinkedIn": "linkedin",
    "Skype": "skype",
}


ID_SCAN_CONTACTS_HEADER = {
    "ID": "profile_id",
    "Ссылка": "profile_url",
    "Имя": "name",
    "Специализация": "title",
    "Email": "email",
    "Телефон": "phone",
    "Telegram": "telegram",
    "WhatsApp": "whatsapp",
    "Facebook": "facebook",
    "LinkedIn": "linkedin",
    "Skype": "skype",
    "Почасовая ставка": "hourly_rate",
    "Top навыки": "skills_top",
}


async def ojp_idscan_command(update, context):
    args = context.args or []
    max_id = int(args[0]) if args and args[0].isdigit() else 1000000
    status = await update.message.reply_text(f"⏳ Запуск ID сканера 0-{max_id:,}")
    try:
        import subprocess
        import re
        
        # Read and modify MAX_ID in scanner script
        scanner_path = "/Users/aiserver/OPENCLAW BOT/id_range_scanner.py"
        with open(scanner_path) as f:
            content = f.read()
        
        # Replace MAX_ID
        content = re.sub(r'MAX_ID = \d+', f'MAX_ID = {max_id}', content)
        
        with open(scanner_path, 'w') as f:
            f.write(content)
        
        # Start scanner
        cmd = ["/Users/aiserver/OPENCLAW BOT/venv_parse/bin/python", scanner_path]
        subprocess.Popen(cmd, cwd="/Users/aiserver/OPENCLAW BOT")
        
        await status.edit_text(
            f"✅ ID сканер запущен!\n"
            f"Диапазон: 0 - {max_id:,}\n"
            f"📊 /ojp_idscan_progress — проверить прогресс"
        )
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


async def ojp_idscan_progress(update, context):
    results_file = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress/id_scan_results.json")
    if not results_file.exists():
        await update.message.reply_text("❌ Сканер не запущен")
        return
    
    results = json.loads(results_file.read_text())
    total = len(results)
    active = sum(1 for r in results.values() if r.get('status') == 'active')
    locked = sum(1 for r in results.values() if r.get('status') == 'locked')
    not_found = sum(1 for r in results.values() if r.get('status') == 'not_found')
    
    pct = total / 500000 * 100
    
    text = f"📊 <b>ID Scanner Progress</b>\n\n"
    text += f"Проверено: {total:,} / 500,000 ({pct:.1f}%)\n\n"
    text += f"🟢 Active: {active:,} ({active/total*100:.1f}%)\n"
    text += f"🔒 Locked: {locked:,}\n"
    text += f"⚪ Not found: {not_found:,}"
    
    await update.message.reply_text(text, parse_mode="HTML")


async def ojp_idscan_export(update, context):
    print(f"=== COMMAND RECEIVED: ojp_idscan_export ===")
    await update.message.reply_text("⏳ Экспортирую всех (318K профилей)...")
    
    csv_file = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress/ojp_idscan_export.csv")
    
    if csv_file.exists():
        try:
            with open(csv_file, "rb") as f:
                await update.message.reply_document(
                    document=f, 
                    filename="ojp_idscan_export.csv", 
                    caption="📊 Все профили: 318,954"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    else:
        await update.message.reply_text("❌ Файл не найден")


async def ojp_idscan_contacts(update, context):
    results_file = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress/id_scan_results.json")
    if not results_file.exists():
        await update.message.reply_text("❌ Нет данных")
        return
    
    results = json.loads(results_file.read_text())
    
    # Filter profiles with at least one contact
    with_contacts = []
    for r in results.values():
        if r.get('email') or r.get('phone') or r.get('telegram') or r.get('whatsapp') or r.get('facebook') or r.get('linkedin') or r.get('skype'):
            with_contacts.append(r)
    
    if not with_contacts:
        await update.message.reply_text("❌ Нет профилей с контактами")
        return
    
    await send_csv(
        update,
        {"rows": with_contacts, "header": ID_SCAN_CONTACTS_HEADER},
        f"ojp_contacts_{len(with_contacts)}.xlsx",
        f"📱 Профилей с контактами: {len(with_contacts)}",
    )





async def company_command(update, context):
    await bot_ctx.set_pending(update.effective_user.id, "company")
    await update.message.reply_text(
        "🏢 Отправьте ссылку на компанию prian.ru/company/...\n\n"
        "Или выберите:\n"
        "/catalog — каталог всех компаний\n"
        "/enrich — все компании с контактами"
    )


async def enrich_command(update, context):
    user_id = update.effective_user.id
    await bot_ctx.clear_pending(user_id)
    status = await update.message.reply_text(
        "⏳ Собираю контакты 244 компаний (~5 мин)..."
    )
    try:
        result = await run_company_enrich()
        companies = result.get("results", [])
        if companies:
            await send_csv(
                update,
                {"rows": companies, "header": ENRICH_HEADER},
                f"prian_companies_{len(companies)}.csv",
                f"🏢 Компаний: {len(companies)}\n"
                f"☎️ С контактами: {len([c for c in companies if c.get('manager_name')])}\n"
                f"🏠 Объектов: {sum(c.get('total_objects', 0) or 0 for c in companies):,}",
            )
        else:
            await status.edit_text("❌ Компании не найдены")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


async def catalog_command(update, context):
    user_id = update.effective_user.id
    await bot_ctx.clear_pending(user_id)
    status = await update.message.reply_text("⏳ Получаю каталог компаний...")
    try:
        result = await run_company_catalog()
        companies = result.get("results", [])
        if companies:
            await send_csv(
                update,
                {"rows": companies, "header": CATALOG_HEADER},
                f"prian_catalog_{len(companies)}.csv",
                f"🏢 Компаний: {len(companies)}\n"
                f"🏠 Объектов: {sum(c.get('total_objects', 0) or 0 for c in companies):,}",
            )
        else:
            await status.edit_text("❌ Компании не найдены")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


async def handle_url(update, context):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    pending = await bot_ctx.get_pending(user_id)

    if pending == "company":
        await bot_ctx.clear_pending(user_id)
        
        if url.lower() in ("catalog", "каталог", "все", "all"):
            await catalog_command(update, context)
            return

        if url.lower() in ("enrich", "обогатить", "контакты", "contacts"):
            await enrich_command(update, context)
            return

        if is_company_catalog_url(url):
            await catalog_command(update, context)
            return

        if not is_company_url(url):
            await update.message.reply_text(
                "❌ Только ссылки prian.ru/company/...\n\n"
                "/catalog — каталог компаний\n"
                "/enrich — компании с контактами"
            )
            return

        status = await update.message.reply_text("⏳ Загружаю информацию о компании...")
        try:
            result = await run_company_parser(url)
            name = result.get("company_name", "—")
            lines = [f"🏢 <b>{name}</b>"]
            objs = result.get("total_objects", 0)
            if objs:
                lines.append(f"🏠 Объектов: {objs:,}")
            countries = result.get("countries", [])
            if countries and isinstance(countries, list):
                lines.append(f"🌍 Страны: {', '.join(countries)}")
            mgr = result.get("manager_name", "")
            if mgr:
                lines.append(f"\n👤 {mgr}")
                pos = result.get("manager_position", "")
                if pos:
                    lines.append(f"   {pos}")
                lng = result.get("manager_languages", "")
                if lng:
                    lines.append(f"   {lng}")
            phones = result.get("phones", [])
            if phones:
                lines.append(f"\n📞 {', '.join(phones)}")
            emails = result.get("emails", [])
            if emails:
                lines.append(f"📧 {', '.join(emails)}")
            wa = result.get("whatsapp", "")
            if wa:
                lines.append(f"💬 {wa}")
            tg = result.get("telegram", "")
            if tg:
                lines.append(f"✈️ {tg}")
            desc = result.get("description", "")
            if desc and len(desc) > 20:
                lines.append(f"\n💬 {desc[:200]}...")
            await status.edit_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    if pending == "prian":
        if not is_prian_url(url):
            await update.message.reply_text("❌ Только ссылки с prian.ru")
            return
        status = await update.message.reply_text("⏳ Парсинг prian.ru...")
        try:
            result = await run_prian_parser(url)
            records = result.get("records", [])
            csv_path = result.get("csv_path", "")
            if records and csv_path and Path(csv_path).exists():
                with open(csv_path, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=f"prian_{len(records)}_objects.csv",
                        caption=f"✅ Найдено: {len(records)} объектов",
                    )
            elif records:
                await send_csv(
                    update,
                    {"rows": records, "header": PRIAN_HEADER},
                    f"prian_{len(records)}_objects.csv",
                    f"✅ Найдено: {len(records)} объектов",
                )
            else:
                await status.edit_text("❌ Объекты не найдены")
        except Exception as e:
            await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    if pending != "parse":
        return

    if not is_avito_url(url):
        await update.message.reply_text("❌ Только Avito ссылки")
        return

    status = await update.message.reply_text("⏳ Парсинг Avito...")

    try:
        result = await run_parser(url)
        xlsx_path = result.get("xlsx")

        if xlsx_path and Path(xlsx_path).exists():
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_path, read_only=True)
            ws = wb.active
            row_count = sum(1 for _ in ws.rows)
            wb.close()
            with open(xlsx_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"✅ {max(0, row_count - 1)} строк | {result.get('duration', 0)}сек",
                )
        else:
            await status.edit_text("❌ Файл не создан. Попробуйте другую ссылку.")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}")


async def run_parser(url):
    loop = asyncio.get_event_loop()

    def _run():
        import time
        start = time.time()
        before = set(RESULT_DIR.glob("*.xlsx"))
        try:
            cmd = [
                "/Users/aiserver/OPENCLAW BOT/venv_parse/bin/python",
                "/Users/aiserver/OPENCLAW BOT/parser_avito/parser_cls.py",
                "--url", url,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           cwd="/Users/aiserver/OPENCLAW BOT/parser_avito")
            all_files = list(RESULT_DIR.glob("*.xlsx"))
            new_files = [f for f in all_files if f not in before]
            if new_files or all_files:
                latest = max(new_files if new_files else all_files, key=lambda p: p.stat().st_mtime)
                return {"status": "done", "duration": round(time.time() - start, 1), "xlsx": str(latest)}
            return {"status": "no_file", "duration": round(time.time() - start, 1)}
        except Exception as e:
            return {"status": "error", "duration": round(time.time() - start, 1), "error": str(e)}

    return await loop.run_in_executor(None, _run)


async def run_prian_parser(url):
    import httpx

    if "/company/" in url and ".html" in url:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "http://127.0.0.1:8001/parse/company",
                json={"urls": [url]}
            )
            data = resp.json()
            results = data.get("results", [])
            if results and results[0].get("ok"):
                return results[0].get("data", {})
            err = results[0].get("error", "") if results else data.get("error", "Parse failed")
            raise Exception(err)

    async with httpx.AsyncClient(timeout=1800) as client:
        resp = await client.post(
            "http://127.0.0.1:8001/parse/prian",
            json={"urls": [url]}
        )
        data = resp.json()
        results = data.get("results", [])
        if results and results[0].get("ok"):
            return results[0].get("data", {})
        err = results[0].get("error", "") if results else data.get("error", "Parse failed")
        raise Exception(err)


async def run_company_parser(url):
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "http://127.0.0.1:8001/parse/company",
            json={"urls": [url]}
        )
        data = resp.json()
        results = data.get("results", [])
        if results and results[0].get("ok"):
            return results[0].get("data", {})
        err = results[0].get("error", "") if results else data.get("error", "Parse failed")
        raise Exception(err)


async def run_company_catalog():
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "http://127.0.0.1:8001/parse/company",
            json={"urls": [], "mode": "catalog"}
        )
        return resp.json()


async def run_company_enrich():
    import httpx

    async with httpx.AsyncClient(timeout=900) as client:
        resp = await client.post(
            "http://127.0.0.1:8001/parse/company",
            json={"urls": [], "mode": "enrich"}
        )
        return resp.json()


async def contacts_command(update, context):
    try:
        stats = agent.get_stats()
        lines = [
            f"📊 <b>База контактов</b>",
            f"",
            f"Всего компаний: {stats['total']}",
            f"С телефонами: {stats['with_phones']}",
            f"С WhatsApp: {stats['with_whatsapp']}",
            f"",
        ]
        if stats.get("by_status"):
            lines.append("<b>По статусам:</b>")
            for s in stats["by_status"]:
                status = s.get("status", "?")
                cnt = s.get("cnt", 0)
                lines.append(f"  {status}: {cnt}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


async def outreach_command(update, context):
    status = await update.message.reply_text("⏳ Загружаю enriched контакты в базу...")
    try:
        result = await run_company_enrich()
        companies = result.get("results", [])
        if not companies:
            await status.edit_text("❌ Нет данных для загрузки. Сначала запустите /enrich")
            return
        ingest = agent.ingest_contacts(companies)
        await status.edit_text(
            f"✅ Контакты загружены!\n\n"
            f"Добавлено: {ingest['inserted']}\n"
            f"Обновлено: {ingest['updated']}\n"
            f"Пропущено: {ingest['skipped']}\n\n"
            f"Используйте /contacts для статистики\n"
            f"Используйте /send <id> для отправкиWhatsApp",
        )
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


async def send_command(update, context):
    args = context.args
    if not args:
        contacts = agent.get_contacts(status="new", has_phone=True, limit=10)
        if not contacts:
            await update.message.reply_text("Нет доступных контактов. Сначала /outreach")
            return
        lines = ["<b>Контакты для отправки:</b>\n"]
        for c in contacts:
            c_id = str(c["id"])[:8]
            name = c.get("manager_name") or c.get("company_name", "—")
            phones = ", ".join(c.get("phones", []) or [])
            wa = c.get("whatsapp", "")
            objs = c.get("total_objects", 0) or 0
            lines.append(f"<code>{c_id}</code> | {name} | {phones} | WA:{'✅' if wa else '❌'} | {objs} объектов")
        lines.append(f"\nОтправить: /send &lt;id&gt;")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    short_id = args[0]
    try:
        contacts = agent.get_contacts(limit=100)
        contact = None
        for c in contacts:
            if str(c["id"]).startswith(short_id):
                contact = c
                break
        if not contact:
            await update.message.reply_text(f"❌ Контакт {short_id} не найден")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка поиска: {str(e)[:100]}")
        return

    cw_configured = agent.chatwoot_configured
    if not cw_configured:
        wa = contact.get("whatsapp", "")
        phones = contact.get("phones", []) or []
        manager = contact.get("manager_name") or contact.get("company_name", "—")
        company = contact.get("company_name", "")
        objs = contact.get("total_objects", 0) or 0
        tg = contact.get("telegram", "")

        greeting = agent._generate_greeting(contact)

        lines = [
            f"⚠️ Chatwoot не настроен. Ссылки для ручной отправки:\n",
            f"🏢 {company} | {objs} объектов",
            f"👤 {manager}",
        ]
        if wa:
            lines.append(f"\n💬 WhatsApp: {wa}")
        if phones:
            for p in phones:
                lines.append(f"📞 Телефон: {p}")
        if tg:
            lines.append(f"✈️ Telegram: {tg}")
        lines.append(f"\n📝 Шаблон сообщения:\n<code>{greeting}</code>")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # Try Chatwoot first, fallback to direct WhatsApp
    sent_via = None
    error_msg = None
    
    # Try Chatwoot
    if agent and agent.chatwoot_configured:
        try:
            conv = agent._ensure_conversation(str(contact["id"]), "whatsapp")
            result = agent.chatwoot_send_message(conv["id"])
            sent_via = "Chatwoot"
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Chatwoot failed: {e}")
    
    # Fallback to direct WhatsApp
    if not sent_via:
        wa_client = get_wa_client()
        try:
            wa_result = await wa_client.send_contact_message(contact)
            if wa_result.get("success"):
                sent_via = "WhatsApp"
            else:
                error_msg = wa_result.get("error", "Unknown error")
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"WhatsApp fallback failed: {e}")
    
    if sent_via:
        await update.message.reply_text(
            f"✅ Отправлено через {sent_via}!\n"
            f"Контакт: {contact.get('manager_name') or contact.get('company_name', '?')}"
        )
    else:
        # Show manual info
        wa = contact.get("whatsapp", "")
        phones = contact.get("phones", []) or []
        greeting = agent._generate_greeting(contact) if agent else "Hi!"
        
        lines = [f"❌ Не удалось отправить автоматически\n"]
        if wa:
            lines.append(f"\n💬 WhatsApp: {wa}")
        if phones:
            for p in phones[:2]:
                lines.append(f"📞 Телефон: {p}")
        lines.append(f"\n📝 Сообщение:\n<code>{greeting[:200]}</code>")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def wa_command(update, context):
    try:
        import whatsapp_desktop
    except ImportError:
        await update.message.reply_text("❌ Модуль WhatsApp Desktop не установлен")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "💬 Отправка через WhatsApp Desktop:\n\n"
            "• /wa <имя> <сообщение> - отправить контакту из базы\n"
            "• /wa <сообщение> - отправить всем новым контактам\n\n"
            "Пример: /wa Иван Привет!"
        )
        return
    
    if len(args) >= 2:
        name = args[0]
        message = " ".join(args[1:])
        
        await update.message.reply_text(f"📤 Отправляю '{message}' контакту '{name}'...")
        
        result = whatsapp_desktop.send_whatsapp_message_by_name(name, message)
        
        if result:
            await update.message.reply_text(f"✅ Сообщение отправлено!")
        else:
            await update.message.reply_text(f"❌ Ошибка отправки. Проверь, что WhatsApp Desktop открыт.")
    else:
        message = " ".join(args)
        await update.message.reply_text(f"📤 Отправляю всем контактам: {message[:50]}...")
        
        contacts = agent.get_contacts(status="new", has_phone=True, limit=5) if agent else []
        
        if not contacts:
            await update.message.reply_text("❌ Нет контактов в базе. Сначала /outreach")
            return
        
        sent = 0
        for c in contacts:
            name = c.get("manager_name") or c.get("company_name", "Unknown")[:20]
            result = whatsapp_desktop.send_whatsapp_message_by_name(name, message)
            if result:
                sent += 1
            await asyncio.sleep(1)
        
        await update.message.reply_text(f"✅ Отправлено {sent}/{len(contacts)} контактам")


async def conversations_command(update, context):
    try:
        convs = agent.get_conversations(limit=20)
        if not convs:
            await update.message.reply_text("Нет диалогов. Используйте /outreach затем /send")
            return
        lines = ["<b>Диалоги:</b>\n"]
        for c in convs:
            c_id = str(c["id"])[:8]
            name = c.get("manager_name") or c.get("company_name", "—")
            channel = c.get("channel", "?")
            stage = c.get("stage", "?")
            status = c.get("status", "?")
            followups = c.get("followup_count", 0)
            lines.append(f"<code>{c_id}</code> | {name} | {channel} | {stage} | {status} | followups: {followups}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")


def main():
    # Get token from config (environment variable)
    token = config.telegram.token
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment!")
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable")
        sys.exit(1)
    
    # Initialize outreach agent lazily
    global agent
    agent = _init_agent()
    
    app = Application.builder().token(token).build()
    
    # Global error handler
    app.add_error_handler(error_handler)
    
    # Core commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("parse", parse_command))
    app.add_handler(CommandHandler("prian", prian_command))
    app.add_handler(CommandHandler("company", company_command))
    app.add_handler(CommandHandler("catalog", catalog_command))
    app.add_handler(CommandHandler("enrich", enrich_command))
    
    # OJP commands
    app.add_handler(CommandHandler("ojp", ojp_command))
    for cmd in OJP_SHORTCUTS:
        app.add_handler(CommandHandler(cmd, ojp_shortcut))
    app.add_handler(CommandHandler("ojp_test", ojp_test_command))
    app.add_handler(CommandHandler("ojp_scan", ojp_scan_start))
    app.add_handler(CommandHandler("ojp_full", ojp_scan_start))
    app.add_handler(CommandHandler("ojp_progress", ojp_progress))
    app.add_handler(CommandHandler("ojp_export", ojp_export))
    
    # ID Scanner commands
    app.add_handler(CommandHandler("ojp_idscan", ojp_idscan_command))
    app.add_handler(CommandHandler("ojp_idscan_progress", ojp_idscan_progress))
    app.add_handler(CommandHandler("ojp_idscan_export", ojp_idscan_export))
    app.add_handler(CommandHandler("export", ojp_idscan_export))
    app.add_handler(CommandHandler("scan", ojp_idscan_contacts))
    
    # Outreach commands
    app.add_handler(CommandHandler("contacts", contacts_command))
    app.add_handler(CommandHandler("outreach", outreach_command))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(CommandHandler("conversations", conversations_command))
    
    # Utility
    app.add_handler(CommandHandler("test", lambda u, c: u.message.reply_text("✅ Bot works!")))
    app.add_handler(CommandHandler("wa", wa_command))

    # Multi-Agent
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("aistatus", ai_status_command))
    app.add_handler(CommandHandler("ai_history", ai_history_command))
    app.add_handler(CommandHandler("ai_stats", ai_stats_command))
    app.add_handler(CommandHandler("ai_analytics", ai_analytics_command))
    app.add_handler(CommandHandler("ai_approvals", ai_approvals_command))
    app.add_handler(CommandHandler("ai_import", ai_import_command))
    
    # Message handler for URLs
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info(f"Bot started v8 | Chatwoot: {'enabled' if config.chatwoot.enabled else 'disabled'}")
    print(f"🤖 OpenClaw Bot v8 started")

    bot_commands = [
        ("ai", "Multi-agent AI ассистент"),
        ("aistatus", "Health статусы агентов"),
        ("ai_history", "История разговора"),
        ("ai_stats", "Performance статистика"),
        ("ai_analytics", "TZ аналитика: воронка, конверсия"),
        ("ai_approvals", "Сообщения на проверке"),
        ("ai_import", "Импорт CSV/XLSX поставщиков"),
        ("start", "Начать / помощь"),
        ("help", "Помощь"),
        ("parse", "Парсить URL"),
        ("prian", "Парсить prian.ru"),
        ("company", "Профиль компании"),
        ("catalog", "Каталог prian.ru"),
        ("enrich", "Обогатить контакты"),
        ("contacts", "Список контактов"),
        ("outreach", "Outreach меню"),
        ("send", "Отправить сообщение"),
        ("wa", "WhatsApp меню"),
        ("scan", "Сканировать OJP ID"),
        ("test", "Тест бота"),
    ]
    app._bot_info = None
    asyncio.get_event_loop().run_until_complete(
        app.bot.set_my_commands(bot_commands)
    )

    app.run_polling(drop_pending_updates=True, timeout=10)


if __name__ == "__main__":
    main()