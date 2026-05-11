"""
AgentOrchestrator — multi-agent router with pipeline support.

Features:
- Keyword + pattern-based routing (fast, deterministic)
- Multi-agent pipelines with data flow between agents
- Auto-chaining: OJP scan → Outreach ingest
- Streaming status callbacks (for Telegram progress)
- Retry + fallback logic
- LLM synthesis (gemma4:26b)
"""

import asyncio
import json
import logging
import time
import uuid
import re
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

from .protocol import Agent, AgentResult, AgentStatus, AgentMessage, MessageType
from .context import AgentContext
from .agents import get_all_agents
from .supervisor import get_supervisor
from .tz_agents import get_tz_agents

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "gemma4:26b"
ROUTING_TIMEOUT = 60.0
AGENT_TIMEOUT = 600.0
MAX_RETRIES = 2


@dataclass
class AgentPlan:
    agents: list[str]
    params: dict
    reasoning: str


@dataclass
class PipelineStep:
    agent_name: str
    params: dict
    depends_on: list[str]
    retry: int = 0


MODELS = [
    ("gemma4:26b", 60.0),
    ("qwen3.5:35b", 90.0),
]


class LLMClient:
    def __init__(self, base_url: str = OLLAMA_URL):
        self.base_url = base_url
        self._models = list(MODELS)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
    ) -> str:
        for model, timeout in self._models:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=timeout) as client:
                    payload = {
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": temperature},
                    }
                    if system:
                        payload["system"] = system
                    resp = await client.post(
                        f"{self.base_url}/api/generate", json=payload
                    )
                    resp.raise_for_status()
                    result = resp.json().get("response", "").strip()
                    if result:
                        logger.debug(f"LLM {model} succeeded ({len(result)} chars)")
                        return result
            except Exception as e:
                logger.warning(f"LLM {model} failed: {e}")
        return f"LLM_ERROR: all models failed"


class AgentOrchestrator:
    """
    Multi-agent orchestrator with pipeline support.

    Supports:
    - Single agent routing
    - Multi-agent pipelines (data flows between agents)
    - Auto-chaining (OJP → Outreach)
    - Status streaming via callback
    - Retry + fallback
    """

    def __init__(self, user_id: int = 0, session_key: str = "default", include_tz: bool = True):
        self.llm = LLMClient()
        self.agents: dict[str, Agent] = {**get_all_agents()}
        if include_tz:
            try:
                self.agents.update(get_tz_agents())
            except Exception:
                pass
        self.user_id = user_id
        self.session_key = session_key
        self.session_id = str(uuid.uuid4())
        self._status_callback: Optional[Callable[[str], Awaitable[None]]] = None

    def set_status_callback(self, cb: Callable[[str], Awaitable[None]]):
        """Set a coroutine callback for status updates (e.g., Telegram edit)."""
        self._status_callback = cb

    async def _status(self, text: str) -> None:
        """Send status update if callback is set."""
        if self._status_callback:
            try:
                await self._status_callback(text)
            except Exception as e:
                logger.warning(f"Status callback failed: {e}")

    async def process(
        self,
        user_message: str,
        context: Optional[AgentContext] = None,
    ) -> dict:
        """
        Process a user message through the multi-agent pipeline.

        Args:
            user_message: The user's text
            context: Shared AgentContext (created if not provided)
            status_callback: Optional coroutine(text) for progress updates

        Returns:
            dict with: response, agent_results, plan, errors, duration
        """
        if context is None:
            context = AgentContext(self.session_id, self.user_id, self.session_key)
            context.ensure_session()

        start_time = time.time()
        results: list[AgentResult] = []
        errors: list[str] = []
        plan: Optional[AgentPlan] = None

        await context.add_turn("user", user_message, "user")

        try:
            await self._status("🤖 Анализирую запрос...")
            plan = await self._route(user_message, context)

            await self._status(
                f"📋 План: {', '.join(plan.agents)}\n⏳ Запускаю..."
            )

            await context.add_turn(
                "system",
                f"[Orch] Plan: {plan.agents} — {plan.reasoning}",
                "orchestrator",
            )

            await self._execute_pipeline(plan, context, results, errors, user_message)

            await self._status("📝 Формирую ответ...")
            response = await self._synthesize(results, errors, context)

        except Exception as e:
            logger.exception(f"Orchestrator error: {e}")
            errors.append(f"Orchestrator: {e}")
            response = f"Произошла ошибка: {e}"

        await context.add_turn("assistant", response, "orchestrator")

        return {
            "response": response,
            "agent_results": [r.to_dict() for r in results],
            "plan": {"agents": plan.agents, "reasoning": plan.reasoning} if plan else None,
            "errors": errors,
            "duration": time.time() - start_time,
            "session_id": self.session_id,
        }

    async def _execute_pipeline(
        self,
        plan: AgentPlan,
        context: AgentContext,
        results: list,
        errors: list,
        user_message: str,
    ) -> None:
        """Execute agents in sequence, passing data between them."""

        for i, agent_name in enumerate(plan.agents):
            agent = self.agents.get(agent_name)
            if not agent:
                errors.append(f"Agent not found: {agent_name}")
                continue

            await self._status(f"🔄 [{i+1}/{len(plan.agents)}] {agent_name}...")

            params = dict(plan.params)

            for attempt in range(MAX_RETRIES + 1):
                try:
                    await context.send_message(
                        from_agent="orchestrator",
                        to_agent=agent_name,
                        msg_type=MessageType.REQUEST,
                        payload={"params": params, "user_message": user_message},
                        correlation_id=str(uuid.uuid4()),
                    )

                    result = await asyncio.wait_for(
                        agent.run(params, context),
                        timeout=AGENT_TIMEOUT,
                    )
                    results.append(result)

                    if result.status == AgentStatus.SUCCESS:
                        await self._status(
                            f"✅ [{i+1}/{len(plan.agents)}] {agent_name} — готово"
                        )

                        if result.data:
                            await context.set_memory(
                                agent_name, "last_result", result.data
                            )

                        try:
                            get_supervisor().log_execution(
                                agent_name=agent_name,
                                session_id=self.session_id,
                                result=result,
                                params=params,
                            )
                        except Exception as e:
                            logger.warning(f"Supervisor log failed: {e}")

                        extracted = self._extract_pipeline_data(result, agent_name)
                        if extracted:
                            params.update(extracted)

                        await self._handle_auto_chain(agent_name, result, context, results, errors)

                        break
                    else:
                        errors.append(f"{agent_name}: {result.error}")
                        if attempt < MAX_RETRIES:
                            await self._status(f"🔁 {agent_name}: retry {attempt+1}/{MAX_RETRIES}")
                        else:
                            await self._status(f"⚠️ {agent_name}: не удалось")

                except asyncio.TimeoutError:
                    result = AgentResult(
                        agent_name=agent_name,
                        status=AgentStatus.TIMEOUT,
                        error=f"Таймаут после {AGENT_TIMEOUT}s",
                    )
                    results.append(result)
                    errors.append(f"{agent_name}: timeout")
                    try:
                        get_supervisor().log_execution(agent_name, self.session_id, result, params)
                    except Exception:
                        pass
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        await self._status(f"⚠️ {agent_name}: ошибка, retry {attempt+1}")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.exception(f"Agent {agent_name} failed: {e}")
                    result = AgentResult(
                        agent_name=agent_name,
                        status=AgentStatus.ERROR,
                        error=str(e),
                    )
                    results.append(result)
                    errors.append(f"{agent_name}: {e}")
                    try:
                        get_supervisor().log_execution(agent_name, self.session_id, result, params)
                    except Exception:
                        pass
                    break

    def _extract_pipeline_data(self, result: AgentResult, agent_name: str) -> dict:
        """Extract data from agent result to pass to next agent in pipeline."""
        data = result.data or {}
        if agent_name == "OJPAgent":
            records = data.get("results", [])
            if records and isinstance(records, list):
                companies = [r for r in records if isinstance(r, dict)]
                if companies:
                    return {"companies": companies}
        return {}

    async def _handle_auto_chain(
        self,
        agent_name: str,
        result: AgentResult,
        context: AgentContext,
        results: list,
        errors: list,
    ) -> None:
        """Automatically trigger downstream agents based on results."""

        if agent_name == "OJPAgent" and result.status == AgentStatus.SUCCESS:
            data = result.data or {}
            records = data.get("results", [])
            contacts_extracted = []

            if records:
                for r in records:
                    if isinstance(r, dict):
                        if r.get("email") or r.get("phone") or r.get("whatsapp"):
                            contacts_extracted.append({
                                "company_id": r.get("profile_id", r.get("job_id", "")),
                                "company_name": r.get("name", r.get("title", "")),
                                "company_url": r.get("url", ""),
                                "phones": [r.get("phone")] if r.get("phone") else [],
                                "emails": [r.get("email")] if r.get("email") else [],
                                "whatsapp": r.get("whatsapp") or "",
                                "telegram": r.get("telegram") or "",
                                "total_objects": 0,
                                "countries": [],
                            })

                if contacts_extracted:
                    await self._status(f"📱 Найдено контактов: {len(contacts_extracted)} → автозагрузка...")

                    outreach = self.agents.get("OutreachAgent")
                    if outreach:
                        try:
                            await context.send_message(
                                from_agent="orchestrator",
                                to_agent="OutreachAgent",
                                msg_type=MessageType.REQUEST,
                                payload={
                                    "params": {"action": "ingest", "companies": contacts_extracted},
                                    "user_message": "auto-chain from OJP",
                                },
                            )
                            chain_result = await asyncio.wait_for(
                                outreach.run({"action": "enrich"}, context),
                                timeout=60.0,
                            )
                            results.append(chain_result)
                            await self._status(f"📤 Outreach: загружено {len(contacts_extracted)} контактов")
                        except Exception as e:
                            errors.append(f"OutreachAgent (auto-chain): {e}")
                            await self._status(f"⚠️ Outreach: {e}")

    async def _route(self, user_message: str, context: AgentContext) -> AgentPlan:
        """Route user message to appropriate agent(s). Uses keyword routing first, LLM as fallback."""

        msg = user_message.strip()
        msg_lower = msg.strip().lower()

        url = ""
        url_match = re.search(r'https?://[^\s]+', msg)
        if url_match:
            url = url_match.group(0)

        try:
            plan = self._route_keyword(msg_lower, msg, url)
            logger.info(f"LLM routing skipped (keyword hit): {plan.agents}")
        except Exception:
            pass
        else:
            return plan

        try:
            plan = await self._route_llm(user_message)
            if plan and plan.agents:
                logger.info(f"LLM routed: {plan.agents} — {plan.reasoning}")
                return plan
        except Exception as e:
            logger.debug(f"LLM routing failed: {e}")

        return self._fallback_route(msg_lower, msg, url)

    def _route_keyword(self, msg_lower: str, msg: str, url: str) -> AgentPlan:
        """Fast keyword + pattern-based routing (primary)."""
        if self._is_pipeline_request(msg_lower):
            return self._route_pipeline(msg_lower, url)

        if "prian.ru" in msg_lower:
            params = {"url": url} if url else {"url": f"https://prian.ru"}
            if "/company/" in msg_lower and "/company/" in url:
                params["mode"] = "company"
            return AgentPlan(agents=["PrianAgent"], params=params, reasoning="URL: prian.ru")

        if "onlinejobs.ph" in msg_lower:
            params = {"url": url, "mode": "jobs"} if url else {"mode": "jobs", "keyword": msg}
            if any(k in msg_lower for k in ["profile", "freelancer", "worker", "va", "virtual"]):
                params["mode"] = "all-profiles"
            return AgentPlan(agents=["OJPAgent"], params=params, reasoning="URL: onlinejobs.ph")

        if "avito.ru" in msg_lower:
            return AgentPlan(agents=["AvitoAgent"], params={"url": url}, reasoning="URL: avito.ru")

        if any(k in msg_lower for k in ["id scan", "id range", "600k", "диапазон"]):
            return AgentPlan(agents=["IDScannerAgent"], params={"max_id": 100000}, reasoning="ID scanner")

        if self._is_ojp_request(msg_lower):
            mode = "all-profiles" if any(k in msg_lower for k in ["profile", "freelancer", "worker", "va", "виртуальн", "ассистент", "freelance"]) else "jobs"
            keyword = self._extract_keyword(msg_lower, msg)
            return AgentPlan(
                agents=["OJPAgent"],
                params={"mode": mode, "keyword": keyword, "max_pages": 10},
                reasoning=f"OJP: {mode}",
            )

        if self._is_outreach_request(msg_lower):
            action = self._detect_outreach_action(msg_lower)
            agents = ["OutreachAgent"]
            if any(k in msg_lower for k in ["enrich", "обогатить"]) and "prian" not in msg_lower:
                agents = ["PrianAgent", "OutreachAgent"]
            return AgentPlan(agents=agents, params={"action": action}, reasoning=f"Outreach: {action}")

        if url:
            return AgentPlan(agents=["PrianAgent"], params={"url": url}, reasoning="URL fallback")

        if self._is_tz_intake_request(msg_lower):
            return AgentPlan(
                agents=["IntakeAgent"],
                params={"source": url or "", "source_type": "file" if url else "list", "records": []},
                reasoning="TZ: intake + qualification",
            )

        if self._is_tz_document_request(msg_lower):
            return AgentPlan(
                agents=["DocumentExtractionAgent"],
                params={"file_path": url},
                reasoning="TZ: document extraction",
            )

        if self._is_tz_conversation_request(msg_lower):
            return AgentPlan(
                agents=["ConversationAgent", "QAComplianceAgent"],
                params={"action": "start"},
                reasoning="TZ: conversation + QA",
            )

        if self._is_tz_crm_request(msg_lower):
            return AgentPlan(
                agents=["CRMSyncAgent"],
                params={"action": "sync"},
                reasoning="TZ: CRM sync",
            )

        return AgentPlan(agents=["PrianAgent"], params={}, reasoning="Default: PrianAgent")

    def _is_pipeline_request(self, msg: str) -> bool:
        """Detect multi-step pipeline requests."""
        pipeline_patterns = [
            ("parse", "enrich"), ("parse", "outreach"), ("parse", "send"),
            ("парсить", "обогатить"), ("парсить", "отправить"), ("парсить", "загрузить"), ("парсить", "контакт"),
            ("сканировать", "загрузить"), ("сканировать", "контакт"), ("сканировать", "обогатить"),
            ("найти", "отправить"), ("найти", "загрузить"), ("найти", "контакт"), ("найти", "обогатить"),
            ("найди", "отправить"), ("найди", "загрузить"), ("найди", "контакт"), ("найди", "обогатить"),
            ("freelancer", "отправить"), ("freelancer", "загрузить"), ("freelancer", "контакт"),
            ("virtual", "отправить"), ("virtual", "загрузить"), ("virtual", "контакт"),
            ("ассистент", "отправить"), ("ассистент", "загрузить"), ("ассистент", "контакт"),
        ]
        for a, b in pipeline_patterns:
            if a in msg and b in msg:
                return True
        return False

    def _is_tz_intake_request(self, msg: str) -> bool:
        kw = ["импорт", "import", "upload", "загрузить список", "csv", "xlsx",
              "квалификац", "qualify", "нормализ", "dedupe", "дедуплик", "список поставщик",
              "new sellers", "new suppliers", "intake"]
        return any(k in msg for k in kw)

    def _is_tz_document_request(self, msg: str) -> bool:
        kw = ["extract", "извлечь", "pdf", "xlsx", "csv", "docx", "document",
              "прайс", "каталог", "catalog", "extract product", "ocr", "parse document",
              "image to text"]
        return any(k in msg for k in kw)

    def _is_tz_conversation_request(self, msg: str) -> bool:
        kw = ["dialog", "диалог", "conversation", "greeting", "приветствие",
              "message", "сообщение", "сценарий", "scenario", "follow up",
              "каталог запрос", "catalog request", "chatwoot"]
        return any(k in msg for k in kw)

    def _is_tz_crm_request(self, msg: str) -> bool:
        kw = ["crm", "sync", "статус", "status", "обновить", "update",
              "карточка", "card", "seller", "поставщик", "analytics",
              "воронка", "funnel"]
        return any(k in msg for k in kw)

    def _route_pipeline(self, msg: str, url: str) -> AgentPlan:
        """Route complex multi-step requests to agent pipeline."""
        agents = []
        params = {}

        if "prian" in msg and "onlinejobs" not in msg and "freelancer" not in msg and "virtual" not in msg:
            agents.append("PrianAgent")
            params = {"url": url} if url else {"url": "https://prian.ru"}
        elif "onlinejobs" in msg or "ojp" in msg or "freelancer" in msg or "virtual" in msg or "ассистент" in msg or "сканировать" in msg:
            agents.append("OJPAgent")
            params = {"url": url, "mode": "all-profiles"} if url else {"mode": "all-profiles", "max_pages": 10}
        elif "prian" in msg:
            agents.append("PrianAgent")
            params = {"url": url} if url else {"url": "https://prian.ru"}
        elif "avito" in msg:
            agents.append("AvitoAgent")
            params = {"url": url} if url else {}

        if any(k in msg for k in ["enrich", "обогатить", "контакт", "загрузить", "отправить"]):
            if "OutreachAgent" not in agents:
                agents.append("OutreachAgent")
            params.setdefault("action", "enrich")

        if not agents:
            agents = ["PrianAgent"]

        return AgentPlan(
            agents=agents,
            params=params,
            reasoning=f"Pipeline: {' → '.join(agents)}",
        )

    async def _route_llm(self, user_message: str) -> Optional[AgentPlan]:
        """Use LLM to route ambiguous requests. Falls back to keyword on timeout."""
        conv_context = ""
        try:
            ctx = AgentContext(str(uuid.uuid4()), 0, "llm_route")
            ctx.ensure_session()
            conv_context = await ctx.get_conversation_for_llm(limit=3)
        except Exception:
            pass

        prompt = f"""User request: {user_message}

Available agents:
- PrianAgent: парсинг prian.ru (недвижимость, компании)
- OJPAgent: парсинг onlinejobs.ph (фрилансеры, виртуальные ассистенты, профили)
- AvitoAgent: парсинг avito.ru
- OutreachAgent: работа с контактами (обогащение, отправка сообщений, WhatsApp)
- IDScannerAgent: массовое сканирование ID диапазонов

Return JSON: {{"agents": ["AgentName"], "params": {{"key": "value"}}, "reasoning": "why"}}

{('Context: ' + conv_context) if conv_context else ''}

Respond ONLY with valid JSON."""

        try:
            result = await asyncio.wait_for(
                self.llm.generate(prompt, temperature=0.1),
                timeout=ROUTING_TIMEOUT,
            )
            if result and not result.startswith("LLM_ERROR"):
                parsed = json.loads(result)
                agents = parsed.get("agents", [])
                if agents:
                    return AgentPlan(
                        agents=agents,
                        params=parsed.get("params", {}),
                        reasoning=parsed.get("reasoning", "LLM routing"),
                    )
        except asyncio.TimeoutError:
            logger.warning("LLM routing timed out")
        except json.JSONDecodeError:
            logger.warning(f"LLM routing gave invalid JSON: {result[:100]}")
        except Exception as e:
            logger.debug(f"LLM routing failed: {e}")
        return None

    def _fallback_route(self, msg_lower: str, msg: str, url: str) -> AgentPlan:
        """Final fallback when keyword and LLM routing both fail."""
        if url:
            return AgentPlan(agents=["PrianAgent"], params={"url": url}, reasoning="URL fallback")
        if self._is_ojp_request(msg_lower):
            return AgentPlan(agents=["OJPAgent"], params={"mode": "jobs", "max_pages": 5}, reasoning="OJP fallback")
        if self._is_outreach_request(msg_lower):
            return AgentPlan(agents=["OutreachAgent"], params={"action": "stats"}, reasoning="Outreach fallback")
        return AgentPlan(agents=["PrianAgent"], params={}, reasoning="Default: PrianAgent")

    def _is_outreach_request(self, msg: str) -> bool:
        outreach_kw = [
            "outreach", "контакт", "отправить", "contact", "send message",
            "whatsapp", "рассылка", "greeting", "follow up", "приветствие",
            "базу", "база контактов",
        ]
        return any(k in msg for k in outreach_kw)

    def _detect_outreach_action(self, msg: str) -> str:
        if any(k in msg for k in ["enrich", "обогатить"]):
            return "enrich"
        if "send" in msg or "отправить" in msg:
            return "send"
        if "follow" in msg:
            return "followup"
        return "stats"

    def _is_ojp_request(self, msg: str) -> bool:
        ojp_kw = [
            "onlinejobs", "ojp", "freelancer", "virtual assistant", "va",
            "philippin", "worker", "кандидат", "профиль", "profile",
            "сканировать", "scan ids", "массовое", "freelance",
            "виртуальн", "ассистент",
        ]
        return any(k in msg for k in ojp_kw)

    def _extract_keyword(self, msg: str, original: str) -> str:
        for domain in ["prian.ru", "avito.ru", "onlinejobs.ph"]:
            if domain in msg:
                parts = original.split(domain)
                if len(parts) > 1:
                    return parts[-1].strip()
        for prefix in ["найти ", "сканировать ", "найди ", "парсить "]:
            if prefix in original.lower():
                return original.lower().replace(prefix, "").strip()
        return original

    async def _synthesize(
        self,
        results: list[AgentResult],
        errors: list[str],
        context: AgentContext,
    ) -> str:
        """Synthesize agent results into a user-friendly response."""

        if not results and errors:
            return f"Ошибка: {errors[0]}"

        successful = [r for r in results if r.status == AgentStatus.SUCCESS]
        if not successful:
            return f"Ни один агент не смог выполнить задачу. Ошибки: {'; '.join(errors[:3])}"

        agent_blocks = []
        for r in successful:
            data = r.data or {}
            if not isinstance(data, dict):
                agent_blocks.append(f"Агент: {r.agent_name}\nСтатус: готово\nДанные: нет данных")
                continue

            lines_detail = []
            total_count = 0

            for key in ["records", "results", "contacts", "profiles", "jobs", "companies"]:
                if key in data and data[key] and isinstance(data[key], (list, dict)):
                    items = data[key] if isinstance(data[key], list) else [data[key]]
                    total_count = len(items)
                    if total_count > 0:
                        sample = items[0] if isinstance(items, list) else items
                        sample_snippet = json.dumps(sample, ensure_ascii=False)[:150] if isinstance(sample, dict) else str(sample)[:80]
                        lines_detail.append(f"  {key}: {total_count} шт (пример: {sample_snippet})")

            ingested = data.get("ingested") or data.get("enriched") or {}
            if isinstance(ingested, dict):
                ins = ingested.get("inserted", 0) or ingested.get("added", 0)
                upd = ingested.get("updated", 0)
                if ins or upd:
                    lines_detail.append(f"  загружено: {ins} новых, {upd} обновлено")

            for num_key in ["count", "total", "found"]:
                if num_key in data and isinstance(data[num_key], (int, float)):
                    total_count = int(data[num_key])
                    if total_count > 0:
                        lines_detail.append(f"  {num_key}: {total_count}")

            block = f"Агент: {r.agent_name}\n"
            block += "\n".join(lines_detail) if lines_detail else "  (без данных)"
            block += f"\nВремя: {r.duration_seconds:.1f}с" if r.duration_seconds else ""
            agent_blocks.append(block)

        memory_context = ""
        try:
            all_mem = await context.get_all_memory()
            if all_mem:
                mem_lines = [f"{k}: {str(v)[:80]}" for k, v in list(all_mem.items())[:6]]
                memory_context = "Предыдущие данные в памяти:\n" + "\n".join(mem_lines)
        except Exception:
            pass

        conv = ""
        try:
            turns = await context.get_conversation(limit=6)
            conv = "\n".join(f"[{t.role}] {t.content[:100]}" for t in turns[:-1])
        except Exception:
            pass

        summary_prompt = f"""Ты — ассистент русскоязычного Telegram-бота для парсинга контактов.

Результаты от агентов:
{chr(10).join(agent_blocks)}

{'Ошибки: ' + ', '.join(errors) if errors else 'Ошибки: нет'}

{memory_context}

{'История разговора (для контекста):' + chr(10) + conv if conv else ''}

Требования к ответу:
- Пиши на русском языке
- Отвечай кратко (1-3 предложения)
- Упомяни конкретные цифры (сколько найдено, загружено, ошибок)
- Если есть ошибки — упомяни их кратко
- Будь дружелюбным и профессиональным
- НЕ повторяй списки и JSON — описывай словами

Ответ:"""

        try:
            llm_response = await self.llm.generate(summary_prompt, temperature=0.35)
            if llm_response and not llm_response.startswith("LLM_ERROR"):
                stripped = llm_response.strip()
                if len(stripped) > 10:
                    return stripped
        except Exception:
            pass

        return self._fallback_synthesis(agent_blocks, errors)

    def _fallback_synthesis(self, agent_blocks: list[str], errors: list[str]) -> str:
        body = "\n\n".join(agent_blocks) if agent_blocks else "Задача выполнена."
        footer = f"\n⚠️ {', '.join(errors)}" if errors else ""
        return body + footer

    async def close(self):
        pass
