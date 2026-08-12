# BTCS Multi-Agent System

A modular multi-agent platform that combines listing parsers, LLM-driven qualification, scenario-based outreach and a Telegram/API control layer around locally served LLMs (Ollama).

![Status](https://img.shields.io/badge/status-prototype-yellow)
![Python](https://img.shields.io/badge/python-3.10-blue)
![LLM](https://img.shields.io/badge/llm-ollama-orange)
![DB](https://img.shields.io/badge/db-postgresql-4169e1)

## Overview

BTCS is a prototype multi-agent system for **B2B lead discovery and outreach**: it ingests seller/listing data from multiple sources (Avito.ru classifieds, prian.ru property portal, OnlineJobs.ph freelancers and jobs), normalizes and scores the records with a local LLM, manages scenario-based conversations with sellers, and routes everything through a common agent protocol backed by PostgreSQL.

The project is a working experiment: real parsers, a real orchestration layer, a real webhook ingestion path and a real Telegram bot are wired together around locally hosted LLM models (no cloud inference).

## Problem

Lead research and outreach for B2B suppliers is manual and fragmented:

- Listings live on different platforms (classifieds, property portals, freelancer job boards), each with its own markup and pagination.
- Raw records need normalization, deduplication and qualification before they are usable.
- First-contact conversations are repetitive and hard to scale.
- Every tool (parser, CRM, messenger) works in isolation, so state and context are lost between steps.

## Solution

BTCS wraps each capability into an **agent** and connects them through a common protocol:

- **AgentOrchestrator** — routes incoming requests to the right agent (keyword/pattern matching first, LLM routing as fallback), executes multi-agent pipelines with data flow between steps, supports auto-chaining (e.g. OJP scan → outreach ingest) and synthesizes a final answer with the LLM.
- **AgentContext** — PostgreSQL-backed shared memory and message bus, so state survives between agents and runs.
- **AgentSupervisor** — tracks executions, health and failure patterns per agent; emits alerts on repeated failures.
- **Webhook ingestion** — a Flask endpoint receives parsed Avito items and pushes them into the orchestration pipeline.
- **FastAPI API (OpenClaw API v2)** — exposes qualification, parsing, conversation and scan endpoints with API-key auth.
- **Telegram bot** — operator-facing commands for parsing, scanning, outreach and AI status.

## Key capabilities

| Capability | Implementation |
|---|---|
| Multi-agent routing & pipelines | `agents/orchestrator.py` — keyword + pattern routing, LLM routing, pipelines, retry/fallback, LLM synthesis |
| Agent protocol | `agents/protocol.py` — `Agent`, `AgentResult`, `AgentMessage`, statuses, message types |
| Shared memory / message bus | `agents/context.py` — PostgreSQL-backed `AgentContext` |
| Health & execution monitoring | `agents/supervisor.py` — `agent_executions`, `agent_health`, `agent_alerts` tables |
| Avito.ru parsing | `AvitoAgent` (`extensions/avito_parser/parse_avito.py`, BeautifulSoup/requests/Playwright) |
| prian.ru parsing (foreign property listings, companies, contacts) | `PrianAgent` (`extensions/prian_parser/`) |
| OnlineJobs.ph parsing & mass profile scanning | `OJPAgent`, `IDScannerAgent` (`extensions/ojp_parser/`, sitemap-based 100K profile scan) |
| B2B outreach (Chatwoot/WhatsApp) | `OutreachAgent` (`extensions/outreach/`, `whatsapp_service/` — Node.js whatsapp-web.js) |
| Seller intake, qualification, documents, CRM sync, QA | TZ agents (`agents/tz_agents.py`): `IntakeAgent`, `ConversationAgent`, `DocumentExtractionAgent`, `CRMSyncAgent`, `QAComplianceAgent` |
| Scenario-driven conversations | `avito-parser-api/scenarios/*.json` — greeting / catalog-request flows |
| Local LLM inference | Ollama (`gemma4:26b`, `qwen3.5:35b`) with model fallback; `OPENCLAW/ollama-proxy.mjs` reverse proxy |

## Architecture

```
                    ┌──────────────────────────────────────────────────┐
 Telegram bot ─────►│                                                  │
                    │            AgentOrchestrator                     │
 Webhook ──────────►│   (routing + pipelines + LLM synthesis)          │
 (Flask :8081)      │                                                  │
                    └───────┬──────────────┬──────────────┬───────────┘
 FastAPI ──────────►        │              │              │
 (uvicorn :8001)            ▼              ▼              ▼
                    ┌──────────────┐ ┌────────────┐ ┌──────────────────┐
                    │  Parsing     │ │  Outreach  │ │  TZ agents       │
                    │  agents      │ │  agent     │ │  (intake, docs,  │
                    │  Avito       │ │  (Chatwoot/│ │   CRM, QA,       │
                    │  Prian       │ │   WhatsApp)│ │   conversation)  │
                    │  OJP / ID    │ └────────────┘ └──────────────────┘
                    └──────┬───────┘
                           │
                    ┌──────▼───────────────────────────────┐
                    │  AgentContext (PostgreSQL)            │
                    │  shared memory + message bus + audit  │
                    └──────┬───────────────────────────────┘
                           │
                    ┌──────▼─────────────┐   ┌──────────────────────┐
                    │  AgentSupervisor   │   │  Ollama (local LLM)  │
                    │  health + alerts   │   │  gemma4:26b / qwen   │
                    └────────────────────┘   └──────────────────────┘
```

Typical flow: parser agent collects records → `IntakeAgent` normalizes and scores them → `ConversationAgent` drives a scenario-based dialog → `CRMSyncAgent` persists seller cards → orchestrator synthesizes the result for the operator.

## Tech stack

- **Python 3.10** — core agents, parsers, API
- **FastAPI + uvicorn** — `avito-parser-api/main.py` (port 8001)
- **Flask** — webhook server (port 8081)
- **python-telegram-bot** — Telegram operator bot (`parse_bot_v6.py`)
- **PostgreSQL / psycopg2** — shared context, audit, seller/conversation storage
- **Ollama** — local LLM inference (`gemma4:26b`, `qwen3.5:35b`) with automatic model fallback
- **Node.js (Express, whatsapp-web.js)** — WhatsApp service (`whatsapp_service/`)
- **Requests / BeautifulSoup / Playwright / urllib** — scraping layer

## Project status

**Prototype.** Functional end-to-end paths exist (parsing → qualification → outreach via API and bot), but the project is an evolving experiment: no dependency manifest or packaging yet, some integrations (e.g. Chatwoot) were implemented and then deferred in practice, and path assumptions (e.g. `/Users/aiserver/...`) are environment-specific.

## My contribution

- Designed and implemented the **multi-agent architecture**: agent protocol, orchestrator with routing/pipelines/fallback, PostgreSQL-backed context, supervisor.
- Built the **webhook ingestion path** and the **FastAPI qualification API** (LLM-based seller scoring, conversation management, parser endpoints).
- Integrated **parsers as agents** (Avito.ru, prian.ru, OnlineJobs.ph) and the **outreach flow** (Chatwoot/WhatsApp).
- Implemented the **TZ agents** (intake, document extraction, CRM sync, QA/compliance) and the **Telegram bot** command surface.

## Quick start

> Note: the repository has no `requirements.txt` yet — install the dependencies used by the modules you run (see imports; e.g. `fastapi`, `uvicorn`, `flask`, `psycopg2`, `httpx`, `python-telegram-bot`, `beautifulsoup4`, `openpyxl`, `pdfplumber`, `pytesseract`, `openai`-compatible Ollama client). Full reproducible setup is TBD.

1. Clone and prepare a `.env` file (see Configuration below; `config.py` loads `.env` automatically).
2. Run Ollama locally (default `http://127.0.0.1:11434`) with the models referenced in config (`gemma4:26b`, `qwen3.5:35b`).
3. Start components:

```bash
# FastAPI (port 8001)
cd avito-parser-api && uvicorn main:app --host 127.0.0.1 --port 8001

# Telegram bot
python parse_bot_v6.py

# Webhook server (port 8081)
python agents/webhook_server.py

# WhatsApp service (port 3000, optional)
cd whatsapp_service && npm install && node index.js

# Or use the launcher:
python run.py [bot|api|all]
```

## Configuration

Environment variables (names only — values live in local `.env`, which is git-ignored):

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`
- `DATABASE_DSN`, `DB_POOL_SIZE`, `DB_TIMEOUT`
- `CHATWOOT_URL`, `CHATWOOT_TOKEN`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_WHATSAPP_INBOX`
- `OJP_API_URL`, `AVITO_RESULT_DIR`, `OJP_PROGRESS_DIR`
- `OLLAMA_URL`, `OLLAMA_MODEL`
- `API_KEY`, `REQUIRE_API_KEY` (FastAPI auth)
- `WEBHOOK_SECRET` (webhook server)

See `config.py` for defaults and loading order (env > `.env` > defaults).

## Limitations

- Prototype quality: no packaging, no CI, no test suite.
- Hard-coded environment paths (`/Users/aiserver/...`) — requires adjustment per machine.
- Third-party site scraping depends on markup that can change without notice.
- Chatwoot integration exists in code but was deferred in active use.
- Client documents (`.docx` etc.) are referenced only as a data format; contents are not exposed.

## Roadmap

- Reproducible environment: dependency manifest, setup script, Docker option.
- Stabilize parser pipelines and add tests.
- Re-enable and validate Chatwoot/WhatsApp outreach end-to-end.

## License

No license file specified.

---

# BTCS Multi-Agent System (RU)

Модульная мультиагентная платформа для сбора объявлений, LLM-квалификации поставщиков, сценарного аутрича и управления через Telegram/API на базе локальных LLM (Ollama).

![Status](https://img.shields.io/badge/status-prototype-yellow)
![Python](https://img.shields.io/badge/python-3.10-blue)
![LLM](https://img.shields.io/badge/llm-ollama-orange)
![DB](https://img.shields.io/badge/db-postgresql-4169e1)

## Обзор

BTCS — прототип мультиагентной системы **B2B-поиска и аутрича**: она забирает данные о продавцах/объявлениях из нескольких источников (Avito.ru, портал зарубежной недвижимости prian.ru, OnlineJobs.ph — фрилансеры и вакансии), нормализует и скорит записи локальной LLM, ведёт сценарные диалоги с продавцами и пропускает все шаги через общий агентный протокол на базе PostgreSQL.

Это рабочий эксперимент: реальные парсеры, оркестрация, webhook-приём данных и Telegram-бот соединены вокруг локальных LLM-моделей (без облачного инференса).

## Проблема

Исследование и аутрич B2B-поставщиков — ручной и разрозненный процесс:

- Объявления живут на разных площадках (классифайды, порталы недвижимости, биржи фриланса) со своей разметкой и пагинацией.
- Сырые записи нужно нормализовать, дедуплицировать и квалифицировать.
- Первичные диалоги шаблонны и плохо масштабируются.
- Инструменты (парсер, CRM, мессенджер) работают изолированно — контекст теряется между шагами.

## Решение

Каждая возможность оформлена как **агент**, соединённый общим протоколом:

- **AgentOrchestrator** — маршрутизация запросов (keyword/pattern, затем LLM-роутинг), мультиагентные pipeline с передачей данных между шагами, auto-chaining (например, OJP-скан → импорт в аутрич), LLM-синтез итогового ответа.
- **AgentContext** — общая память и шина сообщений на PostgreSQL: состояние переживает агентов и запуски.
- **AgentSupervisor** — учёт выполнений, здоровья и паттернов отказов, алерты при повторных сбоях.
- **Webhook-приём** — Flask-эндпоинт принимает распарсенные объявления Avito и передаёт их в оркестратор.
- **FastAPI API (OpenClaw API v2)** — эндпоинты квалификации, парсинга, диалогов и сканирования с авторизацией по API-ключу.
- **Telegram-бот** — команды оператора для парсинга, сканирования, аутрича и статуса AI.

## Ключевые возможности

| Возможность | Реализация |
|---|---|
| Маршрутизация и pipeline | `agents/orchestrator.py` — роутинг, пайплайны, retry/fallback, LLM-синтез |
| Агентный протокол | `agents/protocol.py` — `Agent`, `AgentResult`, `AgentMessage`, статусы |
| Общая память / шина | `agents/context.py` — `AgentContext` на PostgreSQL |
| Мониторинг агентов | `agents/supervisor.py` — таблицы `agent_executions`, `agent_health`, `agent_alerts` |
| Парсинг Avito.ru | `AvitoAgent` (`extensions/avito_parser/`) |
| Парсинг prian.ru (объявления, компании, контакты) | `PrianAgent` (`extensions/prian_parser/`) |
| OnlineJobs.ph: вакансии и массовый скан профилей | `OJPAgent`, `IDScannerAgent` (`extensions/ojp_parser/`, скан 100K профилей по sitemap) |
| B2B-аутрич (Chatwoot/WhatsApp) | `OutreachAgent` (`extensions/outreach/`, `whatsapp_service/` — Node.js whatsapp-web.js) |
| Импорт, квалификация, документы, CRM, QA | TZ-агенты (`agents/tz_agents.py`): `IntakeAgent`, `ConversationAgent`, `DocumentExtractionAgent`, `CRMSyncAgent`, `QAComplianceAgent` |
| Сценарные диалоги | `avito-parser-api/scenarios/*.json` — приветствие / запрос каталога |
| Локальные LLM | Ollama (`gemma4:26b`, `qwen3.5:35b`) с фолбэком; `OPENCLAW/ollama-proxy.mjs` — reverse proxy |

## Архитектура

```
                    ┌──────────────────────────────────────────────────┐
 Telegram-бот ────► │                                                  │
                    │            AgentOrchestrator                     │
 Webhook ─────────► │   (роутинг + pipeline + LLM-синтез)              │
 (Flask :8081)      │                                                  │
                    └───────┬──────────────┬──────────────┬───────────┘
 FastAPI ──────────►        │              │              │
 (uvicorn :8001)            ▼              ▼              ▼
                    ┌──────────────┐ ┌────────────┐ ┌──────────────────┐
                    │  Агенты      │ │  Аутрич    │ │  TZ-агенты       │
                    │  парсинга    │ │  (Chatwoot/│ │  (intake, docs,  │
                    │  Avito       │ │   WhatsApp)│ │   CRM, QA,       │
                    │  Prian       │ └────────────┘ │   диалоги)       │
                    │  OJP / ID    │                └──────────────────┘
                    └──────┬───────┘
                           │
                    ┌──────▼───────────────────────────────┐
                    │  AgentContext (PostgreSQL)            │
                    │  общая память + шина + аудит          │
                    └──────┬───────────────────────────────┘
                           │
                    ┌──────▼─────────────┐   ┌──────────────────────┐
                    │  AgentSupervisor   │   │  Ollama (локальная   │
                    │  здоровье+алерты   │   │  LLM) gemma4/qwen    │
                    └────────────────────┘   └──────────────────────┘
```

Типовой поток: агент-парсер собирает записи → `IntakeAgent` нормализует и скорит → `ConversationAgent` ведёт сценарный диалог → `CRMSyncAgent` сохраняет карточки → оркестратор синтезирует результат оператору.

## Технологии

- **Python 3.10** — ядро, парсеры, API
- **FastAPI + uvicorn** — `avito-parser-api/main.py` (порт 8001)
- **Flask** — webhook-сервер (порт 8081)
- **python-telegram-bot** — Telegram-бот оператора (`parse_bot_v6.py`)
- **PostgreSQL / psycopg2** — общий контекст, аудит, карточки/диалоги
- **Ollama** — локальные LLM (`gemma4:26b`, `qwen3.5:35b`) с автоматическим фолбэком
- **Node.js (Express, whatsapp-web.js)** — WhatsApp-сервис (`whatsapp_service/`)
- **Requests / BeautifulSoup / Playwright / urllib** — слой скрейпинга

## Статус проекта

**Прототип.** Рабочие сквозные пути (парсинг → квалификация → аутрич через API и бота) есть, но проект — развивающийся эксперимент: нет манифеста зависимостей и упаковки, часть интеграций (например, Chatwoot) реализована, но на практике отложена, пути в коде завязаны на конкретное окружение (`/Users/aiserver/...`).

## Мой вклад

- Спроектировал и реализовал **мультиагентную архитектуру**: агентный протокол, оркестратор с роутингом/pipeline/fallback, контекст на PostgreSQL, супервизор.
- Построил **webhook-приём данных** и **FastAPI API квалификации** (LLM-скоринг продавцов, управление диалогами, эндпоинты парсеров).
- Интегрировал **парсеры как агентов** (Avito.ru, prian.ru, OnlineJobs.ph) и **поток аутрича** (Chatwoot/WhatsApp).
- Реализовал **TZ-агентов** (intake, извлечение документов, CRM-синхронизация, QA/compliance) и **команды Telegram-бота**.

## Быстрый старт

> В репозитории пока нет `requirements.txt` — установите зависимости используемых модулей (см. импорты: `fastapi`, `uvicorn`, `flask`, `psycopg2`, `httpx`, `python-telegram-bot`, `beautifulsoup4`, `openpyxl`, `pdfplumber`, `pytesseract` и т.п.). Полное воспроизводимое окружение — TBD.

1. Склонируйте и подготовьте `.env` (см. Configuration; `config.py` подхватывает `.env` автоматически).
2. Запустите Ollama локально (по умолчанию `http://127.0.0.1:11434`) с моделями из конфига (`gemma4:26b`, `qwen3.5:35b`).
3. Запустите компоненты:

```bash
# FastAPI (порт 8001)
cd avito-parser-api && uvicorn main:app --host 127.0.0.1 --port 8001

# Telegram-бот
python parse_bot_v6.py

# Webhook-сервер (порт 8081)
python agents/webhook_server.py

# WhatsApp-сервис (порт 3000, опционально)
cd whatsapp_service && npm install && node index.js

# Или лаунчер:
python run.py [bot|api|all]
```

## Конфигурация

Переменные окружения (только имена; значения — в локальном `.env`, он в .gitignore):

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`
- `DATABASE_DSN`, `DB_POOL_SIZE`, `DB_TIMEOUT`
- `CHATWOOT_URL`, `CHATWOOT_TOKEN`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_WHATSAPP_INBOX`
- `OJP_API_URL`, `AVITO_RESULT_DIR`, `OJP_PROGRESS_DIR`
- `OLLAMA_URL`, `OLLAMA_MODEL`
- `API_KEY`, `REQUIRE_API_KEY` (авторизация FastAPI)
- `WEBHOOK_SECRET` (webhook-сервер)

Дефолты и порядок загрузки — в `config.py` (env > `.env` > дефолты).

## Ограничения

- Качество прототипа: нет упаковки, CI, тестов.
- Жёстко прописанные пути окружения (`/Users/aiserver/...`) — требуют правки под другую машину.
- Скрейпинг сторонних сайтов зависит от разметки, которая меняется без предупреждения.
- Интеграция Chatwoot реализована в коде, но в активной эксплуатации отложена.
- Клиентские документы (`.docx` и др.) упоминаются только как формат данных; содержимое не раскрывается.

## Планы

- Воспроизводимое окружение: манифест зависимостей, скрипт установки, вариант Docker.
- Стабилизация парсер-пайплайнов и тесты.
- Повторное включение и проверка аутрича Chatwoot/WhatsApp end-to-end.

## Лицензия

Файл лицензии не указан.
