"""
OpenClaw Multi-Agent System
Architecture:
  Orchestrator (LLM Router) -> AgentContext (Memory + Message Bus)
                                  -> Agent (PrianAgent, OJPAgent, OutreachAgent, ...)

Agent lifecycle:
  1. Orchestrator receives user message
  2. Orchestrator routes to appropriate agent(s) via LLM
  3. Agent runs with shared AgentContext (state persists across agents)
  4. Agent emits messages (results, errors, status) to context
  5. Other agents can react to messages
  6. Orchestrator synthesizes final response
"""

from .protocol import Agent, AgentResult, AgentStatus, AgentMessage, MessageType
from .context import AgentContext, get_context, reset_context
from .orchestrator import AgentOrchestrator
from .supervisor import AgentSupervisor, get_supervisor
from .agents import get_all_agents
from .tz_agents import get_tz_agents
from .tz_database import TZDatabase

__all__ = [
    "Agent",
    "AgentResult",
    "AgentStatus",
    "AgentMessage",
    "MessageType",
    "AgentContext",
    "get_context",
    "reset_context",
    "AgentOrchestrator",
    "AgentSupervisor",
    "get_supervisor",
    "get_all_agents",
    "get_tz_agents",
    "TZDatabase",
]
