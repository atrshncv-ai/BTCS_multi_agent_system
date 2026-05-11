"""
Agent Supervisor — monitors agent health and execution.

Features:
- Periodic health checks on agent executions (stored in PostgreSQL)
- Tracks agent failure patterns
- Provides /ai/status command with agent health overview
- Logs execution metrics to DB
- Can trigger alerts on repeated failures
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from .protocol import AgentResult

from .context import _get_conn
logger = logging.getLogger(__name__)


def _init_supervisor_tables():
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_executions (
                id SERIAL PRIMARY KEY,
                agent_name VARCHAR(100) NOT NULL,
                session_id UUID,
                status VARCHAR(20) NOT NULL,
                duration_seconds FLOAT,
                error TEXT,
                params JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_health (
                agent_name VARCHAR(100) PRIMARY KEY,
                status VARCHAR(20) NOT NULL,
                last_check TIMESTAMPTZ,
                last_success TIMESTAMPTZ,
                last_error TEXT,
                consecutive_failures INT DEFAULT 0,
                total_executions INT DEFAULT 0,
                total_success INT DEFAULT 0,
                avg_duration FLOAT DEFAULT 0,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_alerts (
                id SERIAL PRIMARY KEY,
                agent_name VARCHAR(100) NOT NULL,
                alert_type VARCHAR(50) NOT NULL,
                message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                acknowledged BOOLEAN DEFAULT FALSE
            )
        """)
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_executions_agent ON agent_executions(agent_name, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_executions_session ON agent_executions(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_acked ON agent_alerts(acknowledged, created_at)",
        ]:
            try:
                cur.execute(sql)
            except Exception:
                pass
        conn.commit()


class AgentSupervisor:
    """
    Monitors agent health and execution patterns.

    Tracks:
    - Agent execution history (success/failure/duration)
    - Consecutive failure counts
    - Average execution times
    - Health status per agent
    - Alerts for repeated failures
    """

    def __init__(self):
        _init_supervisor_tables()
        self._health_task: Optional[asyncio.Task] = None
        self._health_check_interval = 300

    def start_health_monitor(self):
        """Start periodic background health monitoring."""
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_monitor_loop())
            logger.info("Agent health monitor started")

    def stop_health_monitor(self):
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            logger.info("Agent health monitor stopped")

    async def _health_monitor_loop(self):
        while True:
            await asyncio.sleep(self._health_check_interval)
            try:
                self._run_health_checks()
            except Exception as e:
                logger.error(f"Health check error: {e}")

    def _run_health_checks(self):
        """Check all agent health statuses and take action."""
        health = self.get_agent_health()
        for h in health:
            failures = h.get("consecutive_failures", 0)
            agent = h.get("agent_name", "")

            if failures >= 5:
                self._create_critical_alert(agent, failures, h.get("last_error", ""))

    def _create_critical_alert(self, agent_name: str, failures: int, last_error: str):
        """Create a critical alert and log."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT 1 FROM agent_alerts
                    WHERE agent_name = %s AND acknowledged = FALSE
                    AND alert_type = 'critical'
                    AND created_at > NOW() - INTERVAL '1 hour'
                """, (agent_name,))
                if cur.fetchone():
                    return

                cur.execute("""
                    INSERT INTO agent_alerts (agent_name, alert_type, message)
                    VALUES (%s, 'critical', %s)
                """, (
                    agent_name,
                    f"CRITICAL: Agent '{agent_name}' failed {failures} consecutive times. "
                    f"Last error: {last_error[:200]}. Auto-restart recommended.",
                ))
                conn.commit()
                logger.error(f"CRITICAL ALERT: {agent_name} — {failures} failures")
        except Exception as e:
            logger.error(f"Failed to create critical alert: {e}")

    def log_execution(
        self,
        agent_name: str,
        session_id: str,
        result: AgentResult,
        params: dict = None,
    ) -> None:
        """Log an agent execution result to the database."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                status = result.status.value if hasattr(result.status, 'value') else str(result.status)

                cur.execute("""
                    INSERT INTO agent_executions
                    (agent_name, session_id, status, duration_seconds, error, params)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    agent_name,
                    session_id,
                    status,
                    result.duration_seconds,
                    result.error,
                    str(params) if params else None,
                ))

                cur.execute("""
                    INSERT INTO agent_health
                    (agent_name, status, last_check, last_success, last_error,
                     consecutive_failures, total_executions, total_success, avg_duration, updated_at)
                    VALUES (%s, %s, NOW(),
                        CASE WHEN %s = 'success' THEN NOW() ELSE NULL END,
                        CASE WHEN %s != 'success' THEN %s ELSE NULL END,
                        CASE WHEN %s != 'success' THEN 1 ELSE 0 END,
                        1,
                        CASE WHEN %s = 'success' THEN 1 ELSE 0 END,
                        %s,
                        NOW())
                    ON CONFLICT (agent_name) DO UPDATE SET
                        status = EXCLUDED.status,
                        last_check = NOW(),
                        last_success = COALESCE(EXCLUDED.last_success, agent_health.last_success),
                        last_error = COALESCE(EXCLUDED.last_error, agent_health.last_error),
                        consecutive_failures = CASE
                            WHEN EXCLUDED.status = 'success' THEN 0
                            ELSE agent_health.consecutive_failures + 1
                        END,
                        total_executions = agent_health.total_executions + 1,
                        total_success = agent_health.total_success + CASE WHEN EXCLUDED.status = 'success' THEN 1 ELSE 0 END,
                        avg_duration = (
                            (agent_health.avg_duration * agent_health.total_executions + %s)
                            / (agent_health.total_executions + 1)
                        ),
                        updated_at = NOW()
                """, (
                    agent_name, status,
                    status, status, result.error,
                    status, status,
                    result.duration_seconds,
                    result.duration_seconds,
                ))

                conn.commit()

                if status != "success":
                    self._check_failure_threshold(agent_name, result.error)

        except Exception as e:
            logger.error(f"Failed to log execution: {e}")

    def _check_failure_threshold(self, agent_name: str, error: str) -> None:
        """Create alert if agent has too many consecutive failures."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT consecutive_failures FROM agent_health
                    WHERE agent_name = %s
                """, (agent_name,))
                row = cur.fetchone()
                if not row:
                    return

                failures = row[0]
                if failures >= 3:
                    alert_type = "critical" if failures >= 5 else "warning"
                    cur.execute("""
                        INSERT INTO agent_alerts (agent_name, alert_type, message)
                        VALUES (%s, %s, %s)
                    """, (
                        agent_name,
                        alert_type,
                        f"Agent '{agent_name}' failed {failures} times in a row. Last error: {error[:200]}",
                    ))
                    conn.commit()
                    logger.warning(
                        f"ALERT [{alert_type}] {agent_name}: {failures} consecutive failures"
                    )
        except Exception as e:
            logger.error(f"Failed to check failure threshold: {e}")

    def get_agent_health(self, agent_name: str = None) -> list[dict]:
        """Get health status for one or all agents."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                if agent_name:
                    cur.execute("""
                        SELECT * FROM agent_health WHERE agent_name = %s
                    """, (agent_name,))
                else:
                    cur.execute("SELECT * FROM agent_health ORDER BY consecutive_failures DESC")
                cols = [d[0] for d in cur.description]
                results = [dict(zip(cols, row)) for row in cur.fetchall()]
                for r in results:
                    r.pop('updated_at', None)
                return results
        except Exception as e:
            logger.error(f"Failed to get agent health: {e}")
            return []

    def get_recent_executions(self, agent_name: str = None, limit: int = 20) -> list[dict]:
        """Get recent agent executions."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                if agent_name:
                    cur.execute("""
                        SELECT agent_name, status, duration_seconds, error, created_at
                        FROM agent_executions
                        WHERE agent_name = %s
                        ORDER BY created_at DESC LIMIT %s
                    """, (agent_name, limit))
                else:
                    cur.execute("""
                        SELECT agent_name, status, duration_seconds, error, created_at
                        FROM agent_executions
                        ORDER BY created_at DESC LIMIT %s
                    """, (limit,))
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get recent executions: {e}")
            return []

    def get_alerts(self, acknowledged: bool = None, limit: int = 20) -> list[dict]:
        """Get agent alerts."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                if acknowledged is None:
                    cur.execute("""
                        SELECT * FROM agent_alerts
                        ORDER BY created_at DESC LIMIT %s
                    """, (limit,))
                else:
                    cur.execute("""
                        SELECT * FROM agent_alerts
                        WHERE acknowledged = %s
                        ORDER BY created_at DESC LIMIT %s
                    """, (acknowledged, limit))
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get alerts: {e}")
            return []

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Acknowledge an alert."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE agent_alerts SET acknowledged = TRUE
                    WHERE id = %s
                """, (alert_id,))
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to acknowledge alert: {e}")
            return False

    def get_status_summary(self) -> dict:
        """Get a summary of the entire agent system's health."""
        try:
            with _get_conn() as conn:
                cur = conn.cursor()

                cur.execute("SELECT COUNT(*), AVG(duration_seconds) FROM agent_executions WHERE created_at > NOW() - INTERVAL '1 hour'")
                hour_row = cur.fetchone()

                cur.execute("SELECT COUNT(*) FROM agent_executions WHERE created_at > NOW() - INTERVAL '24 hours'")
                day_row = cur.fetchone()

                cur.execute("SELECT COUNT(*) FROM agent_alerts WHERE acknowledged = FALSE AND created_at > NOW() - INTERVAL '24 hours'")
                alert_row = cur.fetchone()

                health = self.get_agent_health()

                healthy = sum(1 for h in health if h.get('consecutive_failures', 0) == 0)
                degraded = sum(1 for h in health if 0 < h.get('consecutive_failures', 0) < 3)
                failing = sum(1 for h in health if h.get('consecutive_failures', 0) >= 3)

                return {
                    "hour_executions": hour_row[0] or 0,
                    "hour_avg_duration": round(hour_row[1], 1) if hour_row[1] else 0,
                    "day_executions": day_row[0] or 0,
                    "active_alerts": alert_row[0] or 0,
                    "agents_healthy": healthy,
                    "agents_degraded": degraded,
                    "agents_failing": failing,
                    "total_agents": len(health),
                }
        except Exception as e:
            logger.error(f"Failed to get status summary: {e}")
            return {}


_supervisor: Optional[AgentSupervisor] = None


def get_supervisor() -> AgentSupervisor:
    """Get or create the global supervisor instance."""
    global _supervisor
    if _supervisor is None:
        _supervisor = AgentSupervisor()
    return _supervisor
