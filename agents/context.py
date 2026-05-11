"""
AgentContext — PostgreSQL-backed shared memory and message bus for multi-agent system.

Replaces subprocess calls and in-memory dicts with persistent state that survives agent deaths.
Every agent reads/writes through this context, enabling real data sharing.
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Any
from dataclasses import dataclass, field

import psycopg2
from psycopg2.extras import RealDictCursor

from .protocol import AgentMessage, MessageType

logger = logging.getLogger(__name__)

DSN = "postgresql://aiserver@localhost/avito_parser"


def _ensure_uuid(value: str) -> str:
    """Convert any string to a valid UUID."""
    try:
        uuid.UUID(value)
        return value
    except (ValueError, TypeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(value)))


def _get_conn():
    return psycopg2.connect(DSN)


def _init_db():
    with _get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id BIGINT NOT NULL,
                session_key VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                metadata JSONB DEFAULT '{}',
                is_active BOOLEAN DEFAULT TRUE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
                from_agent VARCHAR(100) NOT NULL,
                to_agent VARCHAR(100) NOT NULL,
                msg_type VARCHAR(50) NOT NULL,
                payload JSONB DEFAULT '{}',
                priority VARCHAR(20) DEFAULT 'normal',
                correlation_id UUID,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                delivered BOOLEAN DEFAULT FALSE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_shared_memory (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
                agent_name VARCHAR(100) NOT NULL,
                memory_key VARCHAR(255) NOT NULL,
                value JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(session_id, agent_name, memory_key)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_conversation (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                agent_name VARCHAR(100),
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_task_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
                task_key VARCHAR(255) NOT NULL,
                task_data JSONB DEFAULT '{}',
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                error TEXT,
                UNIQUE(session_id, task_key)
            )
        """)

        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON agent_messages(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_to ON agent_messages(to_agent, delivered)",
            "CREATE INDEX IF NOT EXISTS idx_memory_session ON agent_shared_memory(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_conv_session ON agent_conversation(session_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_queue_session ON agent_task_queue(session_id, status)",
        ]:
            try:
                cur.execute(sql)
            except Exception:
                pass

        conn.commit()


@dataclass
class ConversationTurn:
    role: str
    content: str
    agent_name: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class AgentContext:
    """
    Shared context for all agents in a session.
    
    Features:
    - Message bus (agents send/receive messages)
    - Shared memory (cross-agent data sharing)
    - Conversation history (for LLM context window)
    - Task queue (pending work across agents)
    - Full PostgreSQL persistence
    """

    def __init__(self, session_id: str, user_id: int, session_key: str = "default"):
        self.session_id = _ensure_uuid(str(session_id))
        self.user_id = user_id
        self.session_key = session_key
        self._conn = None
        self._lock = asyncio.Lock()
        self._messages_cache: list[AgentMessage] = []
        self._memory_cache: dict[str, Any] = {}

    def _conn_get(self):
        if self._conn is None or self._conn.closed:
            self._conn = _get_conn()
        return self._conn

    def _ensure_session(self):
        conn = self._conn_get()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            INSERT INTO agent_sessions (id, user_id, session_key, is_active)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (id) DO UPDATE SET
                updated_at = NOW(),
                is_active = TRUE
            RETURNING id
        """, (self.session_id, self.user_id, self.session_key))
        conn.commit()
        return self.session_id

    # === MESSAGE BUS ===

    async def send_message(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: MessageType,
        payload: dict,
        priority: str = "normal",
        correlation_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AgentMessage:
        """Send a message from one agent to another (or to orchestrator)."""
        if isinstance(msg_type, str):
            msg_type = MessageType(msg_type)
        if not isinstance(msg_type, MessageType):
            msg_type = MessageType.RESULT

        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            msg_id = str(uuid.uuid4())
            now = datetime.utcnow()

            cur.execute("""
                INSERT INTO agent_messages
                (id, session_id, from_agent, to_agent, msg_type, payload, priority, correlation_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                msg_id,
                self.session_id,
                from_agent,
                to_agent,
                msg_type.value,
                json.dumps(payload),
                priority,
                correlation_id,
                json.dumps(metadata or {}),
            ))
            conn.commit()

            msg = AgentMessage(
                id=msg_id,
                from_agent=from_agent,
                to_agent=to_agent,
                type=msg_type,
                payload=payload,
                priority=priority,
                correlation_id=correlation_id,
                created_at=now,
                metadata=metadata or {},
            )

            if to_agent == "orchestrator" or to_agent == "*":
                self._messages_cache.append(msg)

            return msg

    async def receive_messages(
        self,
        agent_name: str,
        delivered_only: bool = False,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """Receive pending messages for this agent."""
        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            delivered_sql = "AND delivered = TRUE" if delivered_only else ""
            cur.execute(f"""
                SELECT * FROM agent_messages
                WHERE session_id = %s AND to_agent = %s {delivered_sql}
                ORDER BY created_at ASC LIMIT %s
            """, (self.session_id, agent_name, limit))

            messages = []
            for row in cur.fetchall():
                messages.append(AgentMessage(
                    id=str(row["id"]),
                    from_agent=row["from_agent"],
                    to_agent=row["to_agent"],
                    type=MessageType(row["msg_type"]),
                    payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
                    priority=row["priority"],
                    correlation_id=str(row["correlation_id"]) if row["correlation_id"] else None,
                    metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                    created_at=row["created_at"],
                ))

            if messages and not delivered_only:
                ids = [m.id for m in messages]
                cur.execute(
                    "UPDATE agent_messages SET delivered = TRUE WHERE id::text = ANY(%s)",
                    ([str(i) for i in ids],)
                )
                conn.commit()

            return messages

    async def mark_delivered(self, message_ids: list[str]) -> None:
        """Mark messages as delivered."""
        if not message_ids:
            return
        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor()
            cur.execute(
                "UPDATE agent_messages SET delivered = TRUE WHERE id::text = ANY(%s)",
                (message_ids,)
            )
            conn.commit()

    # === SHARED MEMORY ===

    async def set_memory(self, agent_name: str, key: str, value: Any) -> None:
        """Store data that other agents can read."""
        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO agent_shared_memory (session_id, agent_name, memory_key, value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id, agent_name, memory_key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (self.session_id, agent_name, key, json.dumps(value, default=str)))
            conn.commit()

            cache_key = f"{agent_name}:{key}"
            self._memory_cache[cache_key] = value

    async def get_memory(self, agent_name: str, key: str, default: Any = None) -> Any:
        """Retrieve data stored by another agent."""
        cache_key = f"{agent_name}:{key}"
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        conn = self._conn_get()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT value FROM agent_shared_memory
            WHERE session_id = %s AND agent_name = %s AND memory_key = %s
            ORDER BY updated_at DESC LIMIT 1
        """, (self.session_id, agent_name, key))
        row = cur.fetchone()

        if row:
            val = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            self._memory_cache[cache_key] = val
            return val
        return default

    async def get_all_memory(self, agent_filter: str = None) -> dict[str, Any]:
        """Get all memory entries for this session."""
        conn = self._conn_get()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        sql = "SELECT agent_name, memory_key, value FROM agent_shared_memory WHERE session_id = %s"
        params = [self.session_id]
        if agent_filter:
            sql += " AND agent_name = %s"
            params.append(agent_filter)
        cur.execute(sql, params)

        result = {}
        for row in cur.fetchall():
            key = f"{row['agent_name']}:{row['memory_key']}"
            result[key] = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        return result

    # === CONVERSATION HISTORY ===

    async def add_turn(self, role: str, content: str, agent_name: str = None, metadata: dict = None) -> None:
        """Add a conversation turn for LLM context."""
        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_conversation
                (session_id, role, content, agent_name, metadata)
                VALUES (%s, %s, %s, %s, %s)
            """, (self.session_id, role, content, agent_name, json.dumps(metadata or {})))
            conn.commit()

    async def get_conversation(self, limit: int = 20) -> list[ConversationTurn]:
        """Get recent conversation turns."""
        conn = self._conn_get()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT role, content, agent_name, created_at FROM agent_conversation
            WHERE session_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (self.session_id, limit))
        rows = cur.fetchall()
        rows.reverse()
        return [ConversationTurn(
            role=r["role"],
            content=r["content"],
            agent_name=r["agent_name"],
            created_at=r["created_at"],
        ) for r in rows]

    async def get_conversation_for_llm(self, limit: int = 20) -> str:
        """Format conversation history as a string for LLM prompt."""
        turns = await self.get_conversation(limit)
        lines = []
        for t in turns:
            role = t.agent_name or t.role
            lines.append(f"[{role}]: {t.content}")
        return "\n".join(lines)

    # === TASK QUEUE ===

    async def enqueue_task(self, task_key: str, task_data: dict) -> None:
        """Add a task to the session's task queue."""
        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_task_queue (session_id, task_key, task_data, status)
                VALUES (%s, %s, %s, 'pending')
                ON CONFLICT (session_id, task_key) DO NOTHING
            """, (self.session_id, task_key, json.dumps(task_data)))
            conn.commit()

    async def get_pending_tasks(self) -> list[dict]:
        """Get all pending tasks for this session."""
        conn = self._conn_get()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM agent_task_queue
            WHERE session_id = %s AND status = 'pending'
            ORDER BY created_at ASC
        """, (self.session_id,))
        results = []
        for row in cur.fetchall():
            results.append({
                "id": str(row["id"]),
                "task_key": row["task_key"],
                "task_data": json.loads(row["task_data"]) if isinstance(row["task_data"], str) else row["task_data"],
                "created_at": row["created_at"].isoformat(),
            })
        return results

    async def complete_task(self, task_key: str, error: str = None) -> None:
        """Mark a task as completed (or failed)."""
        async with self._lock:
            conn = self._conn_get()
            cur = conn.cursor()
            status = "error" if error else "completed"
            cur.execute("""
                UPDATE agent_task_queue
                SET status = %s, completed_at = NOW(), error = %s, updated_at = NOW()
                WHERE session_id = %s AND task_key = %s
            """, (status, error, self.session_id, task_key))
            conn.commit()

    # === SESSION ===

    def ensure_session(self) -> str:
        """Ensure session exists in DB."""
        try:
            return self._ensure_session()
        except Exception as e:
            logger.warning(f"Failed to ensure session: {e}")
            return self.session_id

    async def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None


_global_context: Optional[AgentContext] = None


def get_context(session_id: str = None, user_id: int = 0, session_key: str = "default") -> AgentContext:
    """Get or create a global AgentContext instance."""
    global _global_context
    if _global_context is None:
        _init_db()
        if session_id is None:
            session_id = str(uuid.uuid4())
        _global_context = AgentContext(session_id, user_id, session_key)
    return _global_context


def reset_context() -> None:
    """Reset global context (useful for testing)."""
    global _global_context
    if _global_context:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_global_context.close())
            else:
                loop.run_until_complete(_global_context.close())
        except Exception:
            pass
    _global_context = None
