"""
Bot Context - manages user state and pending operations.
Replaces global dictionaries for thread-safe operation.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class UserState:
    """State for a single user."""
    pending_action: Optional[str] = None  # 'parse', 'prian', 'company', 'ojp'
    last_command: Optional[str] = None
    last_update: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)


class BotContext:
    """
    Thread-safe context manager for bot user states.
    Replaces global pending_* dictionaries.
    """
    
    def __init__(self):
        self._states: Dict[int, UserState] = {}
        self._lock = asyncio.Lock()
    
    async def set_pending(self, user_id: int, action: str) -> None:
        """Set pending action for user."""
        async with self._lock:
            if user_id not in self._states:
                self._states[user_id] = UserState()
            self._states[user_id].pending_action = action
            self._states[user_id].last_update = datetime.now()
            logger.debug(f"User {user_id}: set pending action = {action}")
    
    async def get_pending(self, user_id: int) -> Optional[str]:
        """Get pending action for user."""
        async with self._lock:
            state = self._states.get(user_id)
            return state.pending_action if state else None
    
    async def clear_pending(self, user_id: int) -> None:
        """Clear pending action for user."""
        async with self._lock:
            if user_id in self._states:
                self._states[user_id].pending_action = None
                self._states[user_id].last_update = datetime.now()
                logger.debug(f"User {user_id}: cleared pending action")
    
    async def has_pending(self, user_id: int) -> bool:
        """Check if user has pending action."""
        async with self._lock:
            state = self._states.get(user_id)
            return state.pending_action is not None if state else False
    
    async def set_metadata(self, user_id: int, key: str, value: any) -> None:
        """Set metadata for user."""
        async with self._lock:
            if user_id not in self._states:
                self._states[user_id] = UserState()
            self._states[user_id].metadata[key] = value
            self._states[user_id].last_update = datetime.now()
    
    async def get_metadata(self, user_id: int, key: str, default=None) -> any:
        """Get metadata for user."""
        async with self._lock:
            state = self._states.get(user_id)
            return state.metadata.get(key, default) if state else default
    
    async def clear_user(self, user_id: int) -> None:
        """Clear all state for user."""
        async with self._lock:
            if user_id in self._states:
                del self._states[user_id]
                logger.debug(f"User {user_id}: cleared all state")
    
    def get_stats(self) -> Dict:
        """Get context statistics."""
        total_users = len(self._states)
        pending_count = sum(1 for s in self._states.values() if s.pending_action)
        return {
            "total_users": total_users,
            "pending_actions": pending_count,
        }


# Global context instance
_context: Optional[BotContext] = None


def get_context() -> BotContext:
    """Get or create global context instance."""
    global _context
    if _context is None:
        _context = BotContext()
    return _context


def reset_context() -> None:
    """Reset global context (useful for testing)."""
    global _context
    _context = None