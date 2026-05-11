from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class MessageType(Enum):
    RESULT = "result"
    ERROR = "error"
    STATUS = "status"
    REQUEST = "request"
    RESPONSE = "response"
    DONE = "done"


@dataclass
class AgentMessage:
    id: str
    from_agent: str
    to_agent: str
    type: MessageType
    payload: dict
    priority: str = "normal"
    correlation_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_name: str
    status: AgentStatus
    data: Optional[dict] = None
    error: Optional[str] = None
    messages: list[AgentMessage] = field(default_factory=list)
    duration_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "messages": [{"type": m.type.value, "payload": m.payload} for m in self.messages],
            "duration": self.duration_seconds,
        }


class Agent(ABC):
    """Abstract base class for all agents in the OpenClaw multi-agent system."""

    def __init__(self):
        self.name = self.__class__.__name__
        self._is_running = False

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        pass

    @property
    def tools(self) -> list[str]:
        """List of tools/APIs this agent uses."""
        return []

    @property
    def supported_intents(self) -> list[str]:
        """List of user intents this agent can handle."""
        return []

    @abstractmethod
    async def run(self, params: dict, context: "AgentContext") -> AgentResult:
        """Execute the agent with given params and shared context."""
        pass

    async def can_handle(self, user_message: str, context: "AgentContext") -> float:
        """Return confidence score (0.0-1.0) that this agent can handle the request."""
        score = 0.0
        msg_lower = user_message.lower()
        for intent in self.supported_intents:
            if intent.lower() in msg_lower:
                score = max(score, 0.6)
        if self.description.lower() in msg_lower:
            score = max(score, 0.4)
        return min(score, 1.0)

    async def on_message(self, message: AgentMessage, context: "AgentContext") -> None:
        """Handle an incoming message from another agent."""
        pass

    async def health_check(self) -> str:
        """Return agent health status."""
        return "healthy" if not self._is_running else "busy"

    async def start(self) -> None:
        self._is_running = False

    async def stop(self) -> None:
        self._is_running = False
