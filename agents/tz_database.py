"""
TZ database schema — расширение AgentContext для ТЗ "Авито Парсер".

Добавляет таблицы:
- tz_sellers (поставщики)
- tz_conversations (диалоги)
- tz_messages (сообщения)
- tz_documents (вложения)
- tz_extracted_products (извлечённые товары)
- tz_scenarios (сценарии общения)
- tz_scenario_templates (шаблоны сообщений)
- tz_audit_logs (аудит)
"""

import json
import logging
from datetime import datetime
from typing import Optional

from .context import _get_conn, _ensure_uuid
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger(__name__)

DSN = "postgresql://aiserver@localhost/avito_parser"


def _init_tz_tables():
    with _get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_sellers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                source_platform VARCHAR(100),
                source_url TEXT,
                seller_name VARCHAR(500),
                seller_id VARCHAR(200) UNIQUE,
                region VARCHAR(200),
                language VARCHAR(10) DEFAULT 'ru',
                category VARCHAR(500),
                relevance_score FLOAT DEFAULT 0.0,
                priority VARCHAR(20) DEFAULT 'medium',
                contact_data JSONB DEFAULT '{}',
                notes TEXT,
                status VARCHAR(50) DEFAULT 'new',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                seller_id UUID REFERENCES tz_sellers(id) ON DELETE SET NULL,
                channel VARCHAR(50) NOT NULL,
                current_stage VARCHAR(100) DEFAULT 'intake',
                status VARCHAR(50) DEFAULT 'active',
                last_message_at TIMESTAMPTZ,
                requires_human_review BOOLEAN DEFAULT FALSE,
                assigned_operator VARCHAR(200),
                session_key VARCHAR(255) UNIQUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                conversation_id UUID REFERENCES tz_conversations(id) ON DELETE CASCADE,
                direction VARCHAR(10) NOT NULL,
                text TEXT,
                template_id VARCHAR(100),
                ai_generated BOOLEAN DEFAULT FALSE,
                moderation_status VARCHAR(50) DEFAULT 'approved',
                sent_at TIMESTAMPTZ,
                received_at TIMESTAMPTZ,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                seller_id UUID REFERENCES tz_sellers(id) ON DELETE SET NULL,
                conversation_id UUID REFERENCES tz_conversations(id) ON DELETE SET NULL,
                file_name VARCHAR(500),
                file_type VARCHAR(50),
                storage_path TEXT,
                parsed_status VARCHAR(50) DEFAULT 'pending',
                uploaded_at TIMESTAMPTZ DEFAULT NOW(),
                metadata JSONB DEFAULT '{}'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_extracted_products (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID REFERENCES tz_documents(id) ON DELETE CASCADE,
                seller_id UUID REFERENCES tz_sellers(id) ON DELETE SET NULL,
                sku VARCHAR(200),
                product_name VARCHAR(500),
                category VARCHAR(200),
                price VARCHAR(100),
                currency VARCHAR(20),
                moq VARCHAR(100),
                lead_time VARCHAR(200),
                notes TEXT,
                confidence FLOAT DEFAULT 0.0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_scenarios (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(200) NOT NULL,
                language VARCHAR(10) DEFAULT 'ru',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_scenario_steps (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                scenario_id UUID REFERENCES tz_scenarios(id) ON DELETE CASCADE,
                step_key VARCHAR(100) NOT NULL,
                step_type VARCHAR(50) NOT NULL,
                template_text TEXT,
                conditions JSONB DEFAULT '{}',
                next_step VARCHAR(100),
                escalation_step VARCHAR(100),
                stop_conditions JSONB DEFAULT '[]',
                sort_order INT DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_audit_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                entity_type VARCHAR(100),
                entity_id UUID,
                action VARCHAR(100) NOT NULL,
                actor_type VARCHAR(50),
                actor_id VARCHAR(200),
                payload JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tz_intake_batches (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                file_name VARCHAR(500),
                record_count INT,
                imported_count INT DEFAULT 0,
                error_count INT DEFAULT 0,
                status VARCHAR(50) DEFAULT 'processing',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_sellers_platform ON tz_sellers(source_platform)",
            "CREATE INDEX IF NOT EXISTS idx_sellers_priority ON tz_sellers(priority)",
            "CREATE INDEX IF NOT EXISTS idx_sellers_status ON tz_sellers(status)",
            "CREATE INDEX IF NOT EXISTS idx_conv_seller ON tz_conversations(seller_id)",
            "CREATE INDEX IF NOT EXISTS idx_conv_status ON tz_conversations(status)",
            "CREATE INDEX IF NOT EXISTS idx_conv_session ON tz_conversations(session_key) WHERE session_key IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_msg_conv ON tz_messages(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_msg_direction ON tz_messages(direction)",
            "CREATE INDEX IF NOT EXISTS idx_doc_seller ON tz_documents(seller_id)",
            "CREATE INDEX IF NOT EXISTS idx_products_doc ON tz_extracted_products(document_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_entity ON tz_audit_logs(entity_type, entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_scenarios_active ON tz_scenarios(is_active)",
        ]:
            try:
                cur.execute(sql)
            except Exception:
                pass

        _seed_default_scenario(cur)

        conn.commit()


def _seed_default_scenario(cur):
    cur.execute("SELECT 1 FROM tz_scenarios LIMIT 1")
    if cur.fetchone():
        return

    cur.execute("""
        INSERT INTO tz_scenarios (id, name, language, is_active)
        VALUES (%s, %s, %s, TRUE)
        RETURNING id
    """, (str(_ensure_uuid("catalog-request-scenario")), "Запрос каталога", "ru"))
    scenario_id = cur.fetchone()[0]

    steps = [
        ("greeting", "message", "Здравствуйте, {seller_name}! Мы заинтересованы в сотрудничестве с поставщиками категории {category}. Можно запросить ваш каталог?", "greeting"),
        ("catalog_request", "message", "Хотелось бы получить ваш каталог и прайс-лист. Какие минимальные объёмы заказа возможны?", "catalog"),
        ("moq_clarify", "message", "Уточните, пожалуйста: MOQ, сроки производства и условия оплаты?", "moq"),
        ("oem_request", "message", "Работаете ли вы по схеме OEM/ODM? Есть ли возможность брендирования?", "oem"),
        ("closing", "message", "Спасибо за информацию! Мы свяжемся с вами для обсуждения деталей.", "closing"),
        ("escalate", "escalate", "Передаю оператору для уточнения деталей.", "escalate"),
    ]

    for i, (key, stype, text, transition) in enumerate(steps):
        cur.execute("""
            INSERT INTO tz_scenario_steps
            (scenario_id, step_key, step_type, template_text, next_step, escalation_step, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            scenario_id, key, stype, text,
            steps[i + 1][0] if i + 1 < len(steps) else None,
            "escalate",
            i,
        ))


class TZDatabase:
    """Доступ к TZ-таблицам."""

    def __init__(self):
        _init_tz_tables()

    def _conn(self):
        return _get_conn()

    def log_audit(
        self,
        action: str,
        entity_type: str = None,
        entity_id: str = None,
        actor_type: str = "agent",
        actor_id: str = None,
        payload: dict = None,
    ):
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO tz_audit_logs
                    (entity_type, entity_id, action, actor_type, actor_id, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    entity_type,
                    _ensure_uuid(entity_id) if entity_id else None,
                    action,
                    actor_type,
                    actor_id,
                    json.dumps(payload or {}),
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Audit log failed: {e}")

    def upsert_seller(self, data: dict) -> str:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            def g(key, default=None):
                v = data.get(key)
                if v is None:
                    return default
                if key == "contact_data" and v:
                    return Json(v) if isinstance(v, dict) else Json({"raw": str(v)})
                return v

            cur.execute("""
                INSERT INTO tz_sellers (source_platform, source_url, seller_name,
                    seller_id, region, language, category, relevance_score, priority,
                    contact_data, notes, status, updated_at)
                VALUES (
                    %(source_platform)s, %(source_url)s, %(seller_name)s,
                    %(seller_id)s, %(region)s, COALESCE(%(language)s, 'ru'),
                    %(category)s, COALESCE(%(relevance_score)s, 0),
                    COALESCE(%(priority)s, 'medium'),
                    %(contact_data)s, %(notes)s,
                    COALESCE(%(status)s, 'new'), NOW()
                )
                ON CONFLICT (seller_id)
                DO UPDATE SET
                    source_platform = COALESCE(EXCLUDED.source_platform, tz_sellers.source_platform),
                    source_url = COALESCE(EXCLUDED.source_url, tz_sellers.source_url),
                    seller_name = COALESCE(EXCLUDED.seller_name, tz_sellers.seller_name),
                    region = COALESCE(EXCLUDED.region, tz_sellers.region),
                    language = COALESCE(EXCLUDED.language, tz_sellers.language),
                    category = COALESCE(EXCLUDED.category, tz_sellers.category),
                    relevance_score = COALESCE(EXCLUDED.relevance_score, tz_sellers.relevance_score),
                    priority = COALESCE(EXCLUDED.priority, tz_sellers.priority),
                    contact_data = COALESCE(EXCLUDED.contact_data, tz_sellers.contact_data),
                    notes = COALESCE(EXCLUDED.notes, tz_sellers.notes),
                    status = COALESCE(EXCLUDED.status, tz_sellers.status),
                    updated_at = NOW()
                RETURNING id
            """, {
                "source_platform": g("source_platform"),
                "source_url": g("source_url"),
                "seller_name": g("seller_name"),
                "seller_id": g("seller_id"),
                "region": g("region"),
                "language": g("language"),
                "category": g("category"),
                "relevance_score": g("relevance_score"),
                "priority": g("priority"),
                "contact_data": g("contact_data"),
                "notes": g("notes"),
                "status": g("status"),
            })
            row = cur.fetchone()
            conn.commit()
            return str(row["id"]) if row else None
            row = cur.fetchone()
            conn.commit()
            return str(row["id"]) if row else None

    def get_seller(self, seller_id: str) -> Optional[dict]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM tz_sellers WHERE id = %s", (_ensure_uuid(seller_id),))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_sellers(self, status: str = None, priority: str = None, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            sql = "SELECT * FROM tz_sellers WHERE 1=1"
            params = []
            if status:
                sql += " AND status = %s"
                params.append(status)
            if priority:
                sql += " AND priority = %s"
                params.append(priority)
            sql += " ORDER BY relevance_score DESC, created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def update_seller_status(self, seller_id: str, status: str):
        self.log_audit("status_change", "seller", seller_id, payload={"status": status})
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tz_sellers SET status = %s, updated_at = NOW() WHERE id = %s",
                (status, _ensure_uuid(seller_id)),
            )
            conn.commit()

    def upsert_conversation(self, seller_id: str, channel: str, session_key: str = None) -> str:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                INSERT INTO tz_conversations (seller_id, channel, session_key, last_message_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (session_key)
                DO UPDATE SET last_message_at = NOW(), updated_at = NOW()
                RETURNING id
            """, (
                _ensure_uuid(seller_id) if seller_id else None,
                channel,
                session_key,
            ))
            row = cur.fetchone()
            conn.commit()
            return str(row["id"]) if row else None

    def add_message(
        self,
        conversation_id: str,
        direction: str,
        text: str,
        template_id: str = None,
        ai_generated: bool = False,
        moderation_status: str = "approved",
        sent_at: datetime = None,
    ) -> str:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                INSERT INTO tz_messages
                (conversation_id, direction, text, template_id, ai_generated,
                 moderation_status, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                _ensure_uuid(conversation_id),
                direction,
                text,
                template_id,
                ai_generated,
                moderation_status,
                sent_at or datetime.utcnow(),
            ))
            row = cur.fetchone()
            cur.execute(
                "UPDATE tz_conversations SET last_message_at = NOW() WHERE id = %s",
                (_ensure_uuid(conversation_id),),
            )
            conn.commit()
            return str(row["id"]) if row else None

    def set_conversation_stage(self, conversation_id: str, stage: str):
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tz_conversations SET current_stage = %s, updated_at = NOW() WHERE id = %s",
                (stage, _ensure_uuid(conversation_id)),
            )
            conn.commit()

    def set_requires_review(self, conversation_id: str, requires: bool):
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tz_conversations SET requires_human_review = %s WHERE id = %s",
                (requires, _ensure_uuid(conversation_id)),
            )
            conn.commit()

    def add_document(
        self,
        seller_id: str,
        conversation_id: str,
        file_name: str,
        file_type: str,
        storage_path: str,
    ) -> str:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                INSERT INTO tz_documents
                (seller_id, conversation_id, file_name, file_type, storage_path)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                _ensure_uuid(seller_id) if seller_id else None,
                _ensure_uuid(conversation_id) if conversation_id else None,
                file_name, file_type, storage_path,
            ))
            row = cur.fetchone()
            conn.commit()
            return str(row["id"]) if row else None

    def add_extracted_products(self, products: list[dict], document_id: str, seller_id: str = None):
        with self._conn() as conn:
            cur = conn.cursor()
            for p in products:
                cur.execute("""
                    INSERT INTO tz_extracted_products
                    (document_id, seller_id, sku, product_name, category, price,
                     currency, moq, lead_time, notes, confidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    _ensure_uuid(document_id),
                    _ensure_uuid(seller_id) if seller_id else None,
                    p.get("sku"), p.get("product_name"), p.get("category"),
                    p.get("price"), p.get("currency"), p.get("moq"),
                    p.get("lead_time"), p.get("notes"), p.get("confidence", 0),
                ))
            conn.commit()

    def get_scenario(self, language: str = "ru") -> Optional[dict]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM tz_scenarios
                WHERE is_active = TRUE AND language = %s
                ORDER BY created_at DESC LIMIT 1
            """, (language,))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    SELECT * FROM tz_scenarios WHERE is_active = TRUE
                    ORDER BY created_at DESC LIMIT 1
                """)
                row = cur.fetchone()
            if not row:
                return None
            scenario = dict(row)
            cur.execute("""
                SELECT * FROM tz_scenario_steps
                WHERE scenario_id = %s
                ORDER BY sort_order
            """, (scenario["id"],))
            scenario["steps"] = [dict(s) for s in cur.fetchall()]
            return scenario

    def get_step(self, scenario_id: str, step_key: str) -> Optional[dict]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM tz_scenario_steps
                WHERE scenario_id = %s AND step_key = %s
            """, (_ensure_uuid(scenario_id), step_key))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_analytics_summary(self) -> dict:
        with self._conn() as conn:
            cur = conn.cursor()

            def count(table, where=""):
                cur.execute(f"SELECT COUNT(*) FROM {table}{where}")
                return cur.fetchone()[0]

            def avg(table, col, where=""):
                cur.execute(f"SELECT AVG({col}) FROM {table} WHERE {col} IS NOT NULL{where}")
                r = cur.fetchone()[0]
                return round(float(r), 1) if r else 0

            return {
                "total_sellers": count("tz_sellers"),
                "new_sellers": count("tz_sellers", " WHERE status = 'new'"),
                "qualified_sellers": count("tz_sellers", " WHERE status = 'qualified'"),
                "active_conversations": count("tz_conversations", " WHERE status = 'active'"),
                "total_messages": count("tz_messages"),
                "ai_generated_messages": count("tz_messages", " WHERE ai_generated = TRUE"),
                "documents_received": count("tz_documents"),
                "products_extracted": count("tz_extracted_products"),
                "avg_relevance_score": avg("tz_sellers", "relevance_score"),
                "requires_review": count("tz_conversations", " WHERE requires_human_review = TRUE"),
                "documents_parsed": count("tz_documents", " WHERE parsed_status = 'done'"),
            }

    def get_pending_approvals(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT m.*, c.channel, c.current_stage, s.seller_name
                FROM tz_messages m
                JOIN tz_conversations c ON m.conversation_id = c.id
                LEFT JOIN tz_sellers s ON c.seller_id = s.id
                WHERE m.moderation_status = 'pending'
                ORDER BY m.created_at DESC
                LIMIT %s
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]