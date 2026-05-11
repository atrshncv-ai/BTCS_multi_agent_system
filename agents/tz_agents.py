"""
TZ Agents — AI-agents по ТЗ "Авито Парсер".

Agent 1 — IntakeAgent: импорт, нормализация, relevance scoring
Agent 2 — ConversationAgent: сценарный диалог, human escalation
Agent 3 — DocumentExtractionAgent: извлечение из PDF/XLSX/CSV/DOCX
Agent 4 — CRMSyncAgent: карточки поставщиков, статусы
Agent 5 — QAComplianceAgent: проверка сообщений, compliance
"""

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from .protocol import Agent, AgentResult, AgentStatus, MessageType
from .context import AgentContext
from .tz_database import TZDatabase

logger = logging.getLogger(__name__)


class IntakeAgent(Agent):
    """
    Agent 1 — Intake & Qualification.

    Принимает CSV/XLSX/JSON списки продавцов, валидирует,
    нормализует, дедуплицирует, считает relevance score.
    """

    @property
    def description(self) -> str:
        return "Import, normalize and qualify seller lists from CSV/XLSX/JSON with relevance scoring"

    @property
    def tools(self) -> list[str]:
        return ["csv", "openpyxl", "psycopg2", "llm"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "import", "загрузить", "upload", "список поставщиков",
            "импорт", "квалификация", "qualify", "csv", "xlsx",
            "normalize", "нормализация", "dedupe", "дедупликация",
        ]

    async def run(self, params: dict, context: AgentContext) -> AgentResult:
        start = time.time()
        db = TZDatabase()
        source = params.get("source") or params.get("file_path")
        source_type = params.get("source_type", "file")
        llm = params.get("_llm")

        await context.add_turn("system", f"[{self.name}] Starting intake from {source}", self.name)

        try:
            if source_type == "file" and source:
                records = await self._load_file(source)
            elif source_type == "list":
                records = params.get("records", [])
            elif source_type == "avito":
                records = await self._scrape_avito(source, llm, context)
            else:
                records = []

            if not records:
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    error="No records to process",
                    duration_seconds=time.time() - start,
                )

            db.log_audit("intake_start", "batch", payload={"count": len(records)})

            results = await self._process_records(records, db, llm, context)
            await context.set_memory(self.name, "last_batch", results)
            await context.set_memory(self.name, "last_run", datetime.utcnow().isoformat())

            db.log_audit(
                "intake_complete",
                "batch",
                payload={
                    "total": len(records),
                    "imported": results.get("imported", 0),
                    "duplicates": results.get("duplicates", 0),
                    "errors": results.get("errors", 0),
                },
            )

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=results,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"IntakeAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    async def _load_file(self, file_path: str) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._load_file_sync, file_path)

    def _load_file_sync(self, file_path: str) -> list[dict]:
        p = Path(file_path)
        if not p.exists():
            return []

        if p.suffix.lower() in (".csv",):
            return self._load_csv(p)
        elif p.suffix.lower() in (".xlsx", ".xls"):
            return self._load_xlsx(p)
        elif p.suffix.lower() == ".json":
            return self._load_json(p)
        return []

    def _load_csv(self, p: Path) -> list[dict]:
        import csv
        records = []
        with open(p, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(self._normalize_row(dict(row)))
        return records

    def _load_xlsx(self, p: Path) -> list[dict]:
        try:
            import openpyxl
        except ImportError:
            logger.warning("openpyxl not available for xlsx reading")
            return []
        records = []
        wb = openpyxl.load_workbook(p, data_only=True)
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            first_row = next(ws.iter_rows(min_row=1, max_row=1), None)
            if not first_row:
                continue
            headers = [str(c.value).strip() if c.value else f"col_{i}" for i, c in enumerate(first_row)]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(row):
                    continue
                d = {h: v for h, v in zip(headers, row) if h}
                records.append(self._normalize_row(d))
        return records

    def _load_json(self, p: Path) -> list[dict]:
        with open(p) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [self._normalize_row(r) for r in data]
        return [self._normalize_row(data)]

    def _normalize_row(self, row: dict) -> dict:
        key_map = {
            "source_platform": ["platform", "source", "источник"],
            "source_url": ["url", "link", "ссылка"],
            "seller_name": ["name", "seller_name", "seller", "название", "компания"],
            "seller_id": ["id", "seller_id", "external_id"],
            "region": ["region", "регион", "location", "город"],
            "category": ["category", "категория", "product_type"],
            "contact_data": ["contact", "контакт", "phone", "email"],
            "notes": ["notes", "заметки", "comment"],
        }
        normalized = {}
        for std_key, variants in key_map.items():
            for vk in variants:
                for rk in row:
                    rk_str = str(rk)
                    if rk_str.lower().strip() == vk.lower():
                        normalized[std_key] = row[rk]
                        break

        if "seller_id" not in normalized or not normalized["seller_id"]:
            normalized["seller_id"] = str(uuid.uuid4())

        normalized["language"] = "ru"
        return normalized

    async def _process_records(
        self,
        records: list[dict],
        db: TZDatabase,
        llm,
        context: AgentContext,
    ) -> dict:
        imported = 0
        duplicates = 0
        errors = 0
        scores = []

        for raw in records:
            try:
                if llm and llm != "stub":
                    scored = await self._score_with_llm(raw, llm)
                else:
                    scored = self._score_rules(raw)
                raw.update(scored)

                seller_id = db.upsert_seller(raw)
                if seller_id:
                    imported += 1
                    if scored.get("relevance_score"):
                        scores.append(scored["relevance_score"])
                else:
                    duplicates += 1

            except Exception as e:
                logger.warning(f"Record processing error: {e}")
                errors += 1

        return {
            "total": len(records),
            "imported": imported,
            "duplicates": duplicates,
            "errors": errors,
            "avg_relevance": round(sum(scores) / len(scores), 2) if scores else 0,
            "high_priority": sum(1 for s in scores if s >= 0.7) if scores else 0,
        }

    def _score_rules(self, record: dict) -> dict:
        score = 0.5
        name = str(record.get("seller_name", "")).lower()
        category = str(record.get("category", "")).lower()
        notes = str(record.get("notes", "")).lower()

        keywords_high = ["производитель", "factory", "manufacturer", "опт", "wholesale", " supplier"]
        keywords_mid = ["дистрибьютор", "importer", "официальн"]
        keywords_bad = ["розница", "retail", "частное", "б/у", "used"]

        text = f"{name} {category} {notes}"
        for kw in keywords_high:
            if kw in text:
                score += 0.2
        for kw in keywords_mid:
            if kw in text:
                score += 0.1
        for kw in keywords_bad:
            if kw in text:
                score -= 0.3

        score = max(0.0, min(1.0, score))

        priority = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"

        return {
            "relevance_score": score,
            "priority": priority,
            "language": self._detect_language(record),
        }

    async def _score_with_llm(self, record: dict, llm) -> dict:
        prompt = f"""Analyze this seller record:

name: {record.get('seller_name', 'N/A')}
category: {record.get('category', 'N/A')}
region: {record.get('region', 'N/A')}
notes: {record.get('notes', 'N/A')}

Return ONLY valid JSON:
{{"relevance_score": 0.0-1.0, "priority": "high|medium|low", "product_categories": ["cat1"], "language": "ru|en", "summary": "one sentence"}}

JSON:"""

        try:
            result = await llm.generate(prompt, temperature=0.1)
            parsed = json.loads(result)
            return {
                "relevance_score": parsed.get("relevance_score", 0.5),
                "priority": parsed.get("priority", "medium"),
                "language": parsed.get("language", "ru"),
                "product_categories": parsed.get("product_categories", []),
            }
        except Exception as e:
            logger.warning(f"LLM scoring failed: {e}, falling back to rules")
            return self._score_rules(record)

    def _detect_language(self, record: dict) -> str:
        text = json.dumps(record, ensure_ascii=False).lower()
        if re.search(r"[а-яё]", text):
            return "ru"
        if re.search(r"[a-z]", text):
            return "en"
        return "ru"

    async def _scrape_avito(self, url: str, llm, context: AgentContext) -> list[dict]:
        await context.add_turn("system", f"[{self.name}] Avito scrape: {url}", self.name)
        return []


class ConversationAgent(Agent):
    """
    Agent 2 — Conversation Agent.

    Ведёт сценарный диалог с поставщиком.
    Генерирует сообщения по шаблонам, определяет stage,
    передаёт оператору при неопределённости.
    """

    @property
    def description(self) -> str:
        return "Scenario-based dialog with sellers: greeting, catalog request, qualification"

    @property
    def tools(self) -> list[str]:
        return ["psycopg2", "llm", "scenario_engine"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "dialog", "диалог", "message", "сообщение", "conversation",
            "greeting", "приветствие", "каталог", "catalog", "прайс",
            "сценарий", "scenario", "follow up", "followup",
        ]

    APPROVAL_MODE = "semi"

    async def run(self, params: dict, context: AgentContext) -> AgentResult:
        start = time.time()
        db = TZDatabase()
        seller_id = params.get("seller_id")
        action = params.get("action", "send_next")

        await context.add_turn("system", f"[{self.name}] Action={action}, seller={seller_id}", self.name)

        try:
            scenario = db.get_scenario(language=params.get("language", "ru"))
            if not scenario:
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    error="No active scenario found",
                    duration_seconds=time.time() - start,
                )

            if action == "start":
                result = await self._start_conversation(seller_id, scenario, db, params)
            elif action == "respond":
                result = await self._process_response(params, db, context)
            elif action == "send_next":
                result = await self._send_next_step(params, scenario, db, context)
            elif action == "escalate":
                result = await self._escalate_to_operator(params, db, context)
            else:
                result = {"warning": f"Unknown action: {action}"}

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=result,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"ConversationAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    async def _start_conversation(
        self,
        seller_id: str,
        scenario: dict,
        db: TZDatabase,
        params: dict,
    ) -> dict:
        channel = params.get("channel", "chatwoot")
        session_key = f"{channel}_{seller_id}"

        conv_id = db.upsert_conversation(seller_id, channel, session_key)
        first_step = next(
            (s for s in scenario.get("steps", []) if s["step_key"] == "greeting"),
            scenario["steps"][0] if scenario.get("steps") else None,
        )

        if not first_step:
            return {"error": "No greeting step in scenario"}

        message_text = self._render_template(
            first_step["template_text"],
            params.get("seller_data", {}),
        )

        approval_needed = self._needs_approval("greeting", params)
        moderation_status = "pending" if approval_needed else "approved"

        msg_id = db.add_message(
            conv_id, "outbound", message_text,
            template_id=first_step["step_key"],
            ai_generated=True,
            moderation_status=moderation_status,
        )

        db.set_conversation_stage(conv_id, first_step["step_key"])
        if approval_needed:
            db.set_requires_review(conv_id, True)

        return {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "message_text": message_text,
            "step": first_step["step_key"],
            "requires_approval": approval_needed,
            "moderation_status": moderation_status,
        }

    async def _send_next_step(
        self,
        params: dict,
        scenario: dict,
        db: TZDatabase,
        context: AgentContext,
    ) -> dict:
        conv_id = params.get("conversation_id")
        current_step = params.get("current_step", "greeting")
        seller_data = params.get("seller_data", {})

        step = next(
            (s for s in scenario["steps"] if s["step_key"] == current_step),
            None,
        )
        if not step:
            return {"error": f"Step {current_step} not found in scenario"}

        next_key = step.get("next_step")
        if not next_key:
            db.set_conversation_stage(conv_id, "completed")
            return {"status": "scenario_completed"}

        next_step = next(
            (s for s in scenario["steps"] if s["step_key"] == next_key),
            None,
        )
        if not next_step:
            return {"status": "no_next_step"}

        message_text = self._render_template(
            next_step["template_text"],
            seller_data,
        )

        approval_needed = self._needs_approval(next_step["step_key"], params)
        moderation_status = "pending" if approval_needed else "approved"

        msg_id = db.add_message(
            conv_id, "outbound", message_text,
            template_id=next_step["step_key"],
            ai_generated=True,
            moderation_status=moderation_status,
        )

        db.set_conversation_stage(conv_id, next_step["step_key"])
        if approval_needed:
            db.set_requires_review(conv_id, True)

        db.log_audit("message_sent", "message", msg_id, payload={
            "step": next_step["step_key"],
            "ai_generated": True,
            "requires_approval": approval_needed,
        })

        return {
            "message_id": msg_id,
            "message_text": message_text,
            "step": next_step["step_key"],
            "requires_approval": approval_needed,
            "moderation_status": moderation_status,
        }

    async def _process_response(
        self,
        params: dict,
        db: TZDatabase,
        context: AgentContext,
    ) -> dict:
        response_text = params.get("response_text", "")
        conv_id = params.get("conversation_id")
        current_step = params.get("current_step", "greeting")

        if self._is_escalation_needed(response_text):
            return await self._escalate_to_operator(params, db, context)

        intent = self._classify_response(response_text)

        recommendations = {
            "catalog": "catalog_request",
            "price": "moq_clarify",
            "oem": "oem_request",
            "closing": "closing",
            "refusal": "escalate",
            "unknown": "escalate",
        }

        recommended_next = recommendations.get(intent, "escalate")

        return {
            "detected_intent": intent,
            "recommended_next_step": recommended_next,
            "requires_human_review": intent in ("refusal", "unknown"),
        }

    def _is_escalation_needed(self, text: str) -> bool:
        escalation_phrases = [
            "не понимаю", "что вы", "кто вы", "спам", "больше не пишите",
            "stop", "unsubscribe", "жалоба", "претензия",
            "юрист", "lawyer", " legal",
        ]
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in escalation_phrases)

    def _classify_response(self, text: str) -> str:
        text_lower = text.lower()

        patterns = {
            "catalog": [r"каталог", r"прайс", r"catalog", r"price.?list", r"список", r"отправ", r"вышл"],
            "price": [r"цен", r"price", r"стоимост", r"руб", r"\$", r"eur", r"usd"],
            "oem": [r"oem", r"odm", r"бренд", r"brand", r"логотип", r"упаковк"],
            "closing": [r"спасибо", r"хорош", r"свяжемся", r"подумаем", r"спасибо", r"thank"],
            "refusal": [r"не интересует", r"не нужно", r"no thanks", r"not interested", r"отказ", r"отказываем"],
        }

        for intent, regexes in patterns.items():
            for rx in regexes:
                if re.search(rx, text_lower):
                    return intent
        return "unknown"

    async def _escalate_to_operator(
        self,
        params: dict,
        db: TZDatabase,
        context: AgentContext,
    ) -> dict:
        conv_id = params.get("conversation_id")
        reason = params.get("reason", "manual escalation")

        db.set_requires_review(conv_id, True)
        db.set_conversation_stage(conv_id, "escalated")
        db.log_audit("escalation", "conversation", conv_id, actor_type="agent", payload={"reason": reason})

        await context.add_turn("system", f"[{self.name}] Escalated conversation {conv_id}", self.name)

        return {
            "status": "escalated",
            "conversation_id": conv_id,
            "reason": reason,
        }

    def _needs_approval(self, step_key: str, params: dict) -> bool:
        mode = params.get("approval_mode", self.APPROVAL_MODE)
        if mode == "manual":
            return True
        if mode == "semi":
            return step_key == "greeting"
        return False

    def _render_template(self, template: str, data: dict) -> str:
        if not template:
            return ""
        result = template
        for key, val in data.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(val))
        return result


class DocumentExtractionAgent(Agent):
    """
    Agent 3 — Document Extraction.

    Обрабатывает PDF/XLSX/CSV/DOCX/JPG/PNG,
    извлекает SKU, наименование, цену, валюту, MOQ,
    срок поставки, упаковку.
    """

    @property
    def description(self) -> str:
        return "Extract structured product data from catalogs, price lists and documents"

    @property
    def tools(self) -> list[str]:
        return ["pdfplumber", "openpyxl", "csv", "llm", "pytesseract", "PIL"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "extract", "извлечение", "документ", "document", "pdf",
            "xlsx", "csv", "прайс", "каталог", "catalog", "parse document",
            "ocr", "image to text",
        ]

    async def run(self, params: dict, context: AgentContext) -> AgentResult:
        start = time.time()
        db = TZDatabase()
        file_path = params.get("file_path")
        seller_id = params.get("seller_id")
        conversation_id = params.get("conversation_id")

        await context.add_turn("system", f"[{self.name}] Processing: {file_path}", self.name)

        try:
            if not file_path:
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    error="No file path provided",
                    duration_seconds=time.time() - start,
                )

            p = Path(file_path)
            if not p.exists():
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    error=f"File not found: {file_path}",
                    duration_seconds=time.time() - start,
                )

            storage_path = self._save_to_storage(p, seller_id)
            doc_id = db.add_document(
                seller_id=seller_id,
                conversation_id=conversation_id,
                file_name=p.name,
                file_type=p.suffix.lower().lstrip("."),
                storage_path=storage_path,
            )

            ext = p.suffix.lower()
            if ext in (".pdf",):
                raw_text = await self._extract_pdf(p)
            elif ext in (".xlsx", ".xls"):
                raw_text = await self._extract_spreadsheet(p)
            elif ext in (".csv",):
                raw_text = await self._extract_csv(p)
            elif ext in (".docx",):
                raw_text = await self._extract_docx(p)
            elif ext in (".jpg", ".jpeg", ".png"):
                raw_text = await self._extract_image(p)
            else:
                raw_text = ""

            llm = params.get("_llm")
            products = await self._extract_products(raw_text, llm, params.get("language", "ru"))

            if products:
                db.add_extracted_products(products, doc_id, seller_id)
                db_conn = db._conn()
                cur = db_conn.cursor()
                cur.execute(
                    "UPDATE tz_documents SET parsed_status = 'done' WHERE id = %s",
                    (uuid.UUID(doc_id),),
                )
                db_conn.commit()

            db.log_audit("document_processed", "document", doc_id, payload={
                "file_name": p.name,
                "products_found": len(products),
            })

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data={
                    "document_id": doc_id,
                    "storage_path": storage_path,
                    "products_extracted": len(products),
                    "products": products[:20],
                    "raw_text_length": len(raw_text),
                },
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"DocumentExtractionAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    def _save_to_storage(self, p: Path, seller_id: str) -> str:
        storage_dir = Path("/Users/aiserver/OPENCLAW BOT/storage/documents")
        if seller_id:
            storage_dir = storage_dir / str(seller_id)[:8]
        storage_dir.mkdir(parents=True, exist_ok=True)
        dest = storage_dir / f"{uuid.uuid4().hex[:8]}_{p.name}"
        import shutil
        shutil.copy2(p, dest)
        return str(dest)

    async def _extract_pdf(self, p: Path) -> str:
        try:
            import pdfplumber
        except ImportError:
            return ""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_pdf_sync, p)

    def _extract_pdf_sync(self, p: Path) -> str:
        import pdfplumber
        texts = []
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages[:20]:
                t = page.extract_text()
                if t:
                    texts.append(t)
        return "\n".join(texts)

    async def _extract_spreadsheet(self, p: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_spreadsheet_sync, p)

    def _extract_spreadsheet_sync(self, p: Path) -> str:
        try:
            import openpyxl
        except ImportError:
            return ""
        texts = []
        wb = openpyxl.load_workbook(p, data_only=True)
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            texts.append(f"[Sheet: {sheet}]")
            for row in ws.iter_rows(values_only=True):
                vals = [str(c) if c is not None else "" for c in row]
                if any(vals):
                    texts.append(" | ".join(vals))
        return "\n".join(texts)

    async def _extract_csv(self, p: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_csv_sync, p)

    def _extract_csv_sync(self, p: Path) -> str:
        import csv
        texts = []
        with open(p, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                texts.append(" | ".join(str(c) for c in row))
        return "\n".join(texts)

    async def _extract_docx(self, p: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_docx_sync, p)

    def _extract_docx_sync(self, p: Path) -> str:
        try:
            from docx import Document
        except ImportError:
            return ""
        texts = []
        doc = Document(p)
        for para in doc.paragraphs:
            if para.text.strip():
                texts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                texts.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(texts)

    async def _extract_image(self, p: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_image_sync, p)

    def _extract_image_sync(self, p: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return "[OCR not available - install pytesseract]"
        img = Image.open(p)
        return pytesseract.image_to_string(img, lang="rus+eng")

    async def _extract_products(self, raw_text: str, llm, language: str) -> list[dict]:
        if not raw_text or len(raw_text.strip()) < 20:
            return []

        if llm and llm != "stub":
            return await self._extract_with_llm(raw_text, llm, language)
        return self._extract_rules_based(raw_text)

    async def _extract_with_llm(self, text: str, llm, language: str) -> list[dict]:
        prompt = f"""Extract product rows from this document text.

Return ONLY a valid JSON array:
[
  {{"sku": "...", "product_name": "...", "category": "...", "price": "...", "currency": "RUB|EUR|USD", "moq": "...", "lead_time": "...", "confidence": 0.9}},
  ...
]

Rules:
- Extract up to 50 products
- price field: the price number or "договорная"/"по запросу" if not found
- currency: detect from symbol (₽=RUB, €=EUR, $=USD)
- moq: minimum order quantity (numbers with units)
- lead_time: delivery/production time
- confidence: 0.0-1.0 based on extraction certainty

Text:
{text[:4000]}

JSON:"""

        try:
            result = await llm.generate(prompt, temperature=0.1)
            if result.startswith("LLM_ERROR"):
                return self._extract_rules_based(text[:3000])
            parsed = json.loads(result)
            if isinstance(parsed, list):
                return [p for p in parsed if p.get("product_name")]
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
        return self._extract_rules_based(text[:3000])

    def _extract_rules_based(self, text: str) -> list[dict]:
        products = []
        lines = text.split("\n")
        price_pattern = re.compile(
            r"([A-Za-zА-Яа-яёЁ][A-Za-zА-Яа-яёЁ\s]{2,50})\s*"
            r"[\|\t,]*\s*"
            r"([\d\s.,]+)\s*"
            r"(₽|руб|\$|€|eur|usd|rub)?",
            re.UNICODE,
        )

        for line in lines:
            line = line.strip()
            if len(line) < 5:
                continue
            m = price_pattern.search(line)
            if m:
                name = m.group(1).strip()
                price_str = m.group(2).strip() if m.group(2) else ""
                currency = self._detect_currency(m.group(3) or "")

                if name and len(name) > 2:
                    products.append({
                        "product_name": name,
                        "price": price_str,
                        "currency": currency,
                        "confidence": 0.5,
                        "moq": "",
                        "lead_time": "",
                        "category": "",
                        "sku": "",
                    })

        return products[:50]

    def _detect_currency(self, text: str) -> str:
        t = text.lower()
        if any(c in t for c in ["₽", "руб", "rub"]):
            return "RUB"
        if any(c in t for c in ["€", "eur"]):
            return "EUR"
        if any(c in t for c in ["$", "usd"]):
            return "USD"
        return "RUB"


class CRMSyncAgent(Agent):
    """
    Agent 4 — CRM/DB Sync.

    Обновляет статусы поставщиков, создаёт карточки,
    синхронизирует результаты с внутренней системой.
    """

    @property
    def description(self) -> str:
        return "Sync seller cards, update statuses, maintain CRM data integrity"

    @property
    def tools(self) -> list[str]:
        return ["psycopg2"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "crm", "sync", "sync", "статус", "status", "обновить",
            "update", "карточка", "card", "seller", "поставщик",
        ]

    async def run(self, params: dict, context: AgentContext) -> AgentResult:
        start = time.time()
        db = TZDatabase()
        action = params.get("action", "sync")
        seller_id = params.get("seller_id")

        await context.add_turn("system", f"[{self.name}] Action={action}", self.name)

        try:
            if action == "sync" and seller_id:
                result = await self._sync_seller(seller_id, params, db, context)
            elif action == "sync_all":
                result = await self._sync_all(params, db, context)
            elif action == "bulk_status":
                result = await self._bulk_status(params, db)
            elif action == "get_card":
                result = await self._get_card(seller_id, db)
            else:
                result = {"warning": f"Unknown action: {action}"}

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=result,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"CRMSyncAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    async def _sync_seller(self, seller_id: str, params: dict, db: TZDatabase, context: AgentContext) -> dict:
        seller = db.get_seller(seller_id)
        if not seller:
            return {"error": f"Seller {seller_id} not found"}

        if params.get("status"):
            db.update_seller_status(seller_id, params["status"])

        await context.set_memory(self.name, f"seller_{seller_id}", seller)
        db.log_audit("seller_sync", "seller", seller_id, payload={"action": "sync", "params": params})

        conversations = self._get_seller_conversations(seller_id, db)
        return {
            "seller_id": seller_id,
            "status": params.get("status", seller.get("status")),
            "conversations": len(conversations),
            "relevance_score": seller.get("relevance_score"),
        }

    def _get_seller_conversations(self, seller_id: str, db: TZDatabase) -> list[dict]:
        with db._conn() as conn:
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM tz_conversations
                WHERE seller_id = %s
                ORDER BY created_at DESC
            """, (_ensure_uuid(seller_id),))
            return [dict(r) for r in cur.fetchall()]

    async def _sync_all(self, params: dict, db: TZDatabase, context: AgentContext) -> dict:
        limit = params.get("limit", 100)
        sellers = db.get_sellers(limit=limit)
        synced = 0
        for s in sellers:
            try:
                await context.set_memory(self.name, f"seller_{s['id']}", dict(s))
                synced += 1
            except Exception:
                pass
        return {"synced": synced, "total": len(sellers)}

    async def _bulk_status(self, params: dict, db: TZDatabase) -> dict:
        updates = params.get("updates", [])
        for u in updates:
            if u.get("seller_id") and u.get("status"):
                try:
                    db.update_seller_status(u["seller_id"], u["status"])
                except Exception:
                    pass
        return {"updated": len(updates)}

    async def _get_card(self, seller_id: str, db: TZDatabase) -> dict:
        seller = db.get_seller(seller_id)
        if not seller:
            return {"error": "Seller not found"}

        convs = self._get_seller_conversations(seller_id, db)
        return {
            "seller": seller,
            "conversations": convs,
            "message_count": sum(
                self._get_message_count(c["id"], db) for c in convs
            ),
        }

    def _get_message_count(self, conv_id: str, db: TZDatabase) -> int:
        with db._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM tz_messages WHERE conversation_id = %s",
                (_ensure_uuid(conv_id),),
            )
            return cur.fetchone()[0]


class QAComplianceAgent(Agent):
    """
    Agent 5 — QA / Compliance.

    Проверяет корректность сообщений, контролирует соблюдение
    сценариев, не допускает отправку рискованных ответов.
    """

    @property
    def description(self) -> str:
        return "Validate AI-generated messages for compliance, safety and scenario adherence"

    @property
    def tools(self) -> list[str]:
        return ["llm", "regex"]

    @property
    def supported_intents(self) -> list[str]:
        return [
            "validate", "проверка", "qa", "compliance", "audit",
            "moderation", "approval", "approve", "reject",
        ]

    async def run(self, params: dict, context: AgentContext) -> AgentResult:
        start = time.time()
        db = TZDatabase()

        action = params.get("action", "validate")

        await context.add_turn("system", f"[{self.name}] Action={action}", self.name)

        try:
            if action == "validate_message":
                result = await self._validate_message(params, db, context)
            elif action == "approve":
                result = self._approve_message(params, db)
            elif action == "reject":
                result = self._reject_message(params, db)
            elif action == "validate_batch":
                result = await self._validate_batch(params, db)
            elif action == "audit":
                result = await self._audit_conversation(params, db)
            else:
                result = {"warning": f"Unknown action: {action}"}

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                data=result,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            logger.exception(f"QAComplianceAgent error: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    RISKY_PATTERNS = [
        r"\b\d{16}\b", r"\b\d{3}-\d{2}-\d{4}\b",
        r"сс\b", r"взятк\b", r"коррупц\b", r"обман\b",
        r"мошенничеств\b", r"фишинг\b",
        r"незаконн\b", r"без лицензи\b",
    ]

    async def _validate_message(self, params: dict, db: TZDatabase, context: AgentContext) -> dict:
        text = params.get("text", "")
        message_id = params.get("message_id")
        scenario_id = params.get("scenario_id")

        flags = []
        warnings = []
        approved = True

        for pattern in self.RISKY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                flags.append(f"risky_pattern: {pattern}")
                approved = False

        if len(text) > 2000:
            flags.append("too_long")
            warnings.append("Message exceeds 2000 chars")

        if not text.strip():
            flags.append("empty")
            approved = False

        llm = params.get("_llm")
        if llm and llm != "stub" and approved:
            llm_result = await self._llm_validate(text, llm)
            if llm_result.get("rejected"):
                approved = False
                warnings.extend(llm_result.get("reasons", []))

        db.log_audit("message_validated", "message", message_id, payload={
            "approved": approved,
            "flags": flags,
            "warnings": warnings,
        })

        return {
            "approved": approved,
            "message_id": message_id,
            "flags": flags,
            "warnings": warnings,
            "action": "block" if not approved else "allow",
        }

    async def _llm_validate(self, text: str, llm) -> dict:
        prompt = f"""Analyze this outreach message for compliance and safety:

"{text}"

Check for:
1. Prohibited claims (fake guarantees, deception)
2. Personal data exposure
3. Spam indicators
4. Violation of platform rules
5. Unprofessional language

Return JSON: {{"rejected": true/false, "reasons": ["reason1"], "score": 0.0-1.0}}

JSON:"""

        try:
            result = await llm.generate(prompt, temperature=0.1)
            return json.loads(result)
        except Exception:
            return {"rejected": False, "reasons": [], "score": 1.0}

    def _approve_message(self, params: dict, db: TZDatabase) -> dict:
        message_id = params.get("message_id")
        if message_id:
            with db._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE tz_messages SET moderation_status = 'approved' WHERE id = %s",
                    (_ensure_uuid(message_id),),
                )
                conv_id = params.get("conversation_id")
                if conv_id:
                    cur.execute(
                        "UPDATE tz_conversations SET requires_human_review = FALSE WHERE id = %s",
                        (_ensure_uuid(conv_id),),
                    )
                conn.commit()
        db.log_audit("message_approved", "message", message_id, actor_type="operator")
        return {"status": "approved", "message_id": message_id}

    def _reject_message(self, params: dict, db: TZDatabase) -> dict:
        message_id = params.get("message_id")
        reason = params.get("reason", "")
        if message_id:
            with db._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE tz_messages SET moderation_status = 'rejected' WHERE id = %s",
                    (_ensure_uuid(message_id),),
                )
                conn.commit()
        db.log_audit("message_rejected", "message", message_id, actor_type="operator", payload={"reason": reason})
        return {"status": "rejected", "message_id": message_id, "reason": reason}

    async def _validate_batch(self, params: dict, db: TZDatabase) -> dict:
        messages = params.get("messages", [])
        results = []
        approved_count = 0

        for msg in messages:
            r = await self._validate_message(msg, db, None)
            results.append(r)
            if r["approved"]:
                approved_count += 1

        return {
            "total": len(messages),
            "approved": approved_count,
            "rejected": len(messages) - approved_count,
            "results": results,
        }

    async def _audit_conversation(self, params: dict, db: TZDatabase) -> dict:
        conv_id = params.get("conversation_id")
        with db._conn() as conn:
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM tz_messages
                WHERE conversation_id = %s
                ORDER BY created_at
            """, (_ensure_uuid(conv_id),))
            messages = [dict(r) for r in cur.fetchall()]

        off_script = 0
        for m in messages:
            if m.get("moderation_status") == "rejected":
                off_script += 1

        return {
            "conversation_id": conv_id,
            "total_messages": len(messages),
            "ai_generated": sum(1 for m in messages if m.get("ai_generated")),
            "rejected": off_script,
            "requires_review": any(m.get("moderation_status") == "pending" for m in messages),
        }


def _ensure_uuid(value: str) -> uuid.UUID:
    try:
        uuid.UUID(str(value))
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return uuid.UUID(str(uuid.uuid5(uuid.NAMESPACE_DNS, str(value))))


def get_tz_agents() -> dict[str, Agent]:
    return {
        "IntakeAgent": IntakeAgent(),
        "ConversationAgent": ConversationAgent(),
        "DocumentExtractionAgent": DocumentExtractionAgent(),
        "CRMSyncAgent": CRMSyncAgent(),
        "QAComplianceAgent": QAComplianceAgent(),
    }