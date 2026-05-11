"""
Agent wrappers — existing scripts wrapped into the Agent protocol.

Each wrapper:
1. Wraps existing parse_* scripts (subprocess calls)
2. Stores results in AgentContext.shared_memory
3. Emits messages to other agents
4. Returns structured AgentResult

The underlying parse scripts are NOT modified.
"""

import asyncio
import json
import subprocess
import time
import uuid
import logging
from datetime import datetime
from pathlib import Path

from .protocol import Agent, AgentResult, AgentStatus, AgentMessage, MessageType

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path("/Users/aiserver/OPENCLAW BOT")
PY = "/opt/homebrew/bin/python3.10"


def _run_sync(script_path: str, args: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Run a script synchronously and return (returncode, stdout, stderr)."""
    cmd = [PY, str(script_path)] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_ROOT,
    )
    return result.returncode, result.stdout, result.stderr


class PrianAgent(Agent):
    """Agent for parsing prian.ru (foreign real estate listings)."""

    PRIAN_PARSER = PROJECT_ROOT / "extensions" / "prian_parser" / "parse_prian.py"
    COMPANY_PARSER = PROJECT_ROOT / "extensions" / "prian_parser" / "parse_company.py"

    @property
    def description(self) -> str:
        return "Parse prian.ru for foreign real estate listings, companies, and agent contacts"

    @property
    def tools(self) -> list[str]:
        return ["urllib.request", "regex", "csv"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "prian", "недвижимость", "real estate", "квартира",
            "дом", "апартаменты", "турция", "испания", "оаэ",
            "prian.ru", "зарубежная", "foreign property",
            "компания", "agent", "контакт",
        ]

    async def run(self, params: dict, context: "AgentContext") -> AgentResult:
        start = time.time()
        url = params.get("url", "")
        mode = params.get("mode", "parse")
        max_items = params.get("max_items", 50)
        max_pages = params.get("max_pages", 3)

        await context.add_turn("system", f"[{self.name}] Starting with url={url}, mode={mode}", self.name)

        try:
            if not url:
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    error="No URL provided",
                )

            if "prian.ru" not in url.lower():
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    error="Not a prian.ru URL",
                )

            if "/company/" in url and ".html" in url:
                result_data = await self._parse_company(url)
            elif "/company/" in url:
                result_data = await self._parse_company_catalog()
            else:
                result_data = await self._parse_listings(url, max_items, max_pages)

            await context.set_memory(self.name, "last_result", result_data)
            await context.set_memory(self.name, "last_url", url)
            await context.set_memory(self.name, "last_run", datetime.utcnow().isoformat())

            if result_data.get("records") and mode != "catalog":
                count = len(result_data["records"])
                await context.send_message(
                    from_agent=self.name,
                    to_agent="orchestrator",
                    msg_type=MessageType.RESULT,
                    payload={"count": count, "data": result_data},
                    metadata={"url": url},
                )

            await context.add_turn(
                "system",
                f"[{self.name}] Completed: {len(result_data.get('records', []))} records",
                self.name,
            )

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=result_data,
                duration_seconds=time.time() - start,
            )

        except asyncio.TimeoutError:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.TIMEOUT,
                error="Parsing timed out",
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            logger.exception(f"PrianAgent error: {e}")
            await context.add_turn("system", f"[{self.name}] Error: {e}", self.name)
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    async def _parse_listings(self, url: str, max_items: int, max_pages: int) -> dict:
        loop = asyncio.get_event_loop()
        rc, stdout, stderr = await loop.run_in_executor(
            None,
            _run_sync,
            self.PRIAN_PARSER,
            ["--url", url, "--max-items", str(max_items), "--max-pages", str(max_pages)],
            1800,
        )
        if rc != 0:
            raise Exception(f"Parser failed: {stderr[:200]}")
        return json.loads(stdout)

    async def _parse_company(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        rc, stdout, stderr = await loop.run_in_executor(
            None,
            _run_sync,
            self.COMPANY_PARSER,
            ["--url", url],
            60,
        )
        if rc != 0:
            raise Exception(f"Company parser failed: {stderr[:200]}")
        return json.loads(stdout)

    async def _parse_company_catalog(self) -> dict:
        loop = asyncio.get_event_loop()
        rc, stdout, stderr = await loop.run_in_executor(
            None,
            _run_sync,
            self.COMPANY_PARSER,
            ["--url", "catalog", "--max-pages", "20"],
            900,
        )
        if rc != 0:
            raise Exception(f"Catalog failed: {stderr[:200]}")
        return {"results": json.loads(stdout), "count": len(json.loads(stdout))}


class OJPAgent(Agent):
    """Agent for scraping onlinejobs.ph (Filipino freelancers and jobs)."""

    OJP_PARSER = PROJECT_ROOT / "extensions" / "ojp_parser" / "parse_ojp.py"
    OJP_SCANNER = PROJECT_ROOT / "extensions" / "ojp_parser" / "scan_profiles.py"

    @property
    def description(self) -> str:
        return "Parse onlinejobs.ph for job listings and freelancer profiles from the Philippines"

    @property
    def tools(self) -> list[str]:
        return ["urllib.request", "regex", "threadpool", "aiohttp"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "onlinejobs", "ojp", "freelancer", "virtual assistant",
            "remote worker", "philippines", "philippino",
            "va", "bpo", "hire", "worker", "candidate",
            "job", "vacancy", "работник", "удалённый",
        ]

    async def run(self, params: dict, context: "AgentContext") -> AgentResult:
        start = time.time()
        mode = params.get("mode", "jobs")
        keyword = params.get("keyword", "")
        max_pages = params.get("max_pages", 3)
        category = params.get("category", "virtual-assistant")

        await context.add_turn("system", f"[{self.name}] Starting mode={mode}", self.name)

        try:
            result_data = await self._run_parser(mode, keyword, max_pages, category)

            await context.set_memory(self.name, "last_result", result_data)
            await context.set_memory(self.name, "last_mode", mode)
            await context.set_memory(self.name, "last_run", datetime.utcnow().isoformat())

            count = len(result_data.get("results", []))
            if count > 0:
                await context.send_message(
                    from_agent=self.name,
                    to_agent="orchestrator",
                    msg_type=MessageType.RESULT,
                    payload={"count": count, "mode": mode, "data": result_data},
                )

            await context.add_turn(
                "system",
                f"[{self.name}] Completed: {count} results",
                self.name,
            )

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=result_data,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"OJPAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    async def _run_parser(self, mode: str, keyword: str, max_pages: int, category: str) -> dict:
        loop = asyncio.get_event_loop()
        args = ["--mode", mode, "--max-pages", str(max_pages)]
        if keyword:
            args += ["--keyword", keyword]
        if category:
            args += ["--category", category]

        timeout = 1800 if mode in ("all-profiles",) else 600 if mode == "all-jobs" else 300
        rc, stdout, stderr = await loop.run_in_executor(
            None,
            _run_sync,
            self.OJP_PARSER,
            args,
            timeout,
        )
        if rc != 0:
            raise Exception(f"OJP parser failed: {stderr[:200]}")
        data = json.loads(stdout)
        return data if isinstance(data, dict) else {"results": data, "count": len(data)}


class OutreachAgentWrapper(Agent):
    """Agent for B2B outreach via Chatwoot/WhatsApp. Wraps existing OutreachAgent."""

    @property
    def description(self) -> str:
        return "B2B outreach automation — ingest contacts, create Chatwoot conversations, send WhatsApp messages"

    @property
    def tools(self) -> list[str]:
        return ["postgresql", "chatwoot_api", "urllib.request"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "outreach", "contact", "message", "whatsapp", "chatwoot",
            "send message", "рассылка", "контакт", "отправить",
            "follow up", "greeting", "приветствие",
            "enrich", "обогатить", "база",
        ]

    async def run(self, params: dict, context: "AgentContext") -> AgentResult:
        start = time.time()
        action = params.get("action", "stats")

        await context.add_turn("system", f"[{self.name}] Action={action}", self.name)

        try:
            from extensions.outreach.outreach_agent import OutreachAgent
            agent = OutreachAgent()

            if not agent.chatwoot_configured:
                await context.send_message(
                    from_agent=self.name,
                    to_agent="orchestrator",
                    msg_type=MessageType.STATUS,
                    payload={"warning": "Chatwoot not configured"},
                )

            if action == "stats":
                result_data = agent.get_stats()
            elif action == "contacts":
                limit = params.get("limit", 50)
                status_filter = params.get("status")
                result_data = {"contacts": agent.get_contacts(status=status_filter, limit=limit)}
            elif action == "send":
                contact_id = params.get("contact_id")
                text = params.get("text")
                if not contact_id:
                    return AgentResult(agent_name=self.name, status=AgentStatus.ERROR, error="No contact_id")
                result = agent.send_message(contact_id, text=text)
                result_data = {"sent": True, **result}
            elif action == "enrich":
                contacts = context.shared_memory.get("prian_companies", [])
                if not contacts:
                    contacts_from_memory = await context.get_all_memory()
                    for key, val in contacts_from_memory.items():
                        if "company" in key.lower() and isinstance(val, dict):
                            if not contacts:
                                contacts = val.get("results", [])
                if contacts:
                    ingest_result = agent.ingest_contacts(contacts)
                    result_data = {"ingested": ingest_result}
                else:
                    result_data = {"ingested": {"inserted": 0, "updated": 0, "skipped": "no contacts found"}}
            elif action == "followup":
                conv_id = params.get("conversation_id")
                if not conv_id:
                    return AgentResult(agent_name=self.name, status=AgentStatus.ERROR, error="No conversation_id")
                result_data = agent.process_followup(conv_id)
            else:
                result_data = {"warning": f"Unknown action: {action}"}

            await context.set_memory(self.name, "last_result", result_data)
            await context.set_memory(self.name, "last_action", action)
            await context.set_memory(self.name, "last_run", datetime.utcnow().isoformat())

            await context.send_message(
                from_agent=self.name,
                to_agent="orchestrator",
                msg_type=MessageType.RESULT,
                payload=result_data,
            )

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=result_data,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"OutreachAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )


class AvitoAgent(Agent):
    """Agent for scraping avito.ru (Russian classifieds)."""

    @property
    def description(self) -> str:
        return "Parse avito.ru for classifieds listings"

    @property
    def tools(self) -> list[str]:
        return ["requests", "beautifulsoup", "playwright"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "avito", "авито", "квартира", "машина", "товар",
            "classifieds", "buy", "sell", "marketplace",
        ]

    async def run(self, params: dict, context: "AgentContext") -> AgentResult:
        start = time.time()
        url = params.get("url", "")
        max_items = params.get("max_items", 50)

        if "avito.ru" not in url.lower():
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error="Not an avito.ru URL",
            )

        try:
            loop = asyncio.get_event_loop()
            parser_script = PROJECT_ROOT / "parser_avito" / "parser_cls.py"

            rc, stdout, stderr = await loop.run_in_executor(
                None,
                _run_sync,
                parser_script,
                ["--url", url],
                120,
            )

            result_data = {"raw_output": stdout, "returncode": rc}
            if rc == 0:
                await context.set_memory(self.name, "last_result", result_data)
                await context.set_memory(self.name, "last_url", url)
            else:
                await context.send_message(
                    from_agent=self.name,
                    to_agent="orchestrator",
                    msg_type=MessageType.ERROR,
                    payload={"error": stderr[:200]},
                )

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS if rc == 0 else AgentStatus.ERROR,
                data=result_data,
                error=None if rc == 0 else stderr[:200],
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"AvitoAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )


class IDScannerAgent(Agent):
    """Agent for mass-scanning onlinejobs.ph profile IDs."""

    ID_SCANNER = PROJECT_ROOT / "id_range_scanner.py"

    @property
    def description(self) -> str:
        return "Mass-scan onlinejobs.ph profile IDs to find active workers with contact info"

    @property
    def tools(self) -> list[str]:
        return ["aiohttp", "regex", "async"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "id scan", "scan ids", "scan profiles", "массовое сканирование",
            "all profiles", "600k", "id range", "диапазон id",
        ]

    async def run(self, params: dict, context: "AgentContext") -> AgentResult:
        start = time.time()
        max_id = params.get("max_id", 100000)

        try:
            await context.add_turn("system", f"[{self.name}] Starting ID scan up to {max_id}", self.name)

            loop = asyncio.get_event_loop()
            rc, stdout, stderr = await loop.run_in_executor(
                None,
                _run_sync,
                self.ID_SCANNER,
                [],
                86400,
            )

            status = AgentStatus.SUCCESS if rc == 0 else AgentStatus.ERROR

            await context.set_memory(self.name, "last_scan_result", {"rc": rc, "stdout_len": len(stdout)})
            await context.set_memory(self.name, "last_run", datetime.utcnow().isoformat())

            return AgentResult(
                agent_name=self.name,
                status=status,
                data={"output_length": len(stdout), "returncode": rc},
                error=stderr[:200] if rc != 0 else None,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"IDScannerAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )


def get_all_agents() -> dict[str, Agent]:
    """Factory: return all registered agents."""
    return {
        "PrianAgent": PrianAgent(),
        "OJPAgent": OJPAgent(),
        "OutreachAgent": OutreachAgentWrapper(),
        "AvitoAgent": AvitoAgent(),
        "IDScannerAgent": IDScannerAgent(),
    }
