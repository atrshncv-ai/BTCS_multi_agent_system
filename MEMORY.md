# MEMORY — OpenClaw Bot Project

## Current State (2026-05-04)

**Bot**: Running on v7 (`parse_bot_v6.py`), python-telegram-bot, venv_parse
**API**: Running on FastAPI port 8001 (`avito-parser-api/main.py`)

## Key Discovery: OJP Sitemap

OnlineJobs.ph has 4 sitemaps:
- `sitemap1.xml` — category/browsing pages (no profiles)
- `sitemap2.xml` — profile IDs 18-64362 (~30K)
- `sitemap3.xml` — profile IDs 64363-118816 (~30K)
- `sitemap4.xml` — profile IDs 118817-177690 (~40K)

**Total: 100,000 unique profile IDs** from sitemaps. This replaces the previous brute-force ID enumeration approach.

## New Commands Added

| Command | Description |
|---------|-------------|
| `/ojp_scan` | Start full scan of all 100K profiles (background thread) |
| `/ojp_progress` | Show scan progress bar |
| `/ojp_export` | Export scanned profiles as XLSX |

## New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/parse/ojp_scan` | POST | Actions: phase1, phase2, export, status, quick, full |
| `/ojp_scan_progress` | GET | Real-time progress |
| `/ojp_scan_export` | GET | Export file info |

## Architecture

- **Phase 1** (seconds): Download 3 sitemaps → extract 100K profile IDs
- **Phase 2** (hours): Fetch each profile detail page, parse fields, save incrementally
- Progress saved to `ojp_progress/scan_progress.json` after each batch of 50
- Results saved to `ojp_progress/profiles.json`
- Can resume from where it left off
- CSV export filters only "active" profiles (with name/description/skills)

## Profile Fields Extracted

profile_id, name, category, hourly_rate, id_proof_score, skills_top, skills_other, overview, description, availability, last_active, url

## Important Notes

- Some sitemap IDs return 404 or empty profiles — handled gracefully
- Profile parsing uses: h1 for category, `jobseeker-name` class for name, Overview/Description/Skills sections
- Chatwoot integration exists but user deferred it ("Пока отмена по функции chatwoot")

## Running Processes

```bash
# API (port 8001)
cd "/Users/aiserver/OPENCLAW BOT/avito-parser-api" && nohup .venv/bin/python main.py > /tmp/parser.log 2>&1 &

# Bot
cd "/Users/aiserver/OPENCLAW BOT" && nohup venv_parse/bin/python parse_bot_v6.py > /tmp/bot.log 2>&1 &
```