"""
Centralized configuration management for OpenClaw Bot.
Loads from environment variables and .env files.
"""

import os
import json
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class TelegramConfig:
    token: str = ""
    allowed_users: List[int] = field(default_factory=list)


@dataclass
class DatabaseConfig:
    dsn: str = "postgresql://aiserver@localhost/avito_parser"
    pool_size: int = 5
    timeout: int = 30


@dataclass
class ChatwootConfig:
    url: str = ""
    token: str = ""
    account_id: str = ""
    whatsapp_inbox: str = ""
    enabled: bool = False


@dataclass
class ParserConfig:
    ojp_api_url: str = "http://127.0.0.1:8001"
    avito_result_dir: Path = field(default_factory=lambda: Path("/Users/aiserver/OPENCLAW BOT/parser_avito/result"))
    ojp_progress_dir: Path = field(default_factory=lambda: Path("/Users/aiserver/OPENCLAW BOT/ojp_progress"))


@dataclass
class AIConfig:
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "gemma4:26b"


@dataclass
class Config:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    chatwoot: ChatwootConfig = field(default_factory=ChatwootConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    ai: AIConfig = field(default_factory=AIConfig)

    # Bot state directory
    bot_data_dir: Path = field(default_factory=lambda: Path("/Users/aiserver/OPENCLAW BOT"))


def load_env_file(env_path: Path) -> None:
    """Load environment variables from .env file."""
    if not env_path.exists():
        return
    
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key and val:
                os.environ.setdefault(key, val)


def get_config(env_file: Optional[Path] = None) -> Config:
    """
    Build Config from environment variables.
    
    Priority: env vars > .env file > defaults
    """
    # Load .env files in order if no specific file provided
    if env_file is None:
        base_path = Path(__file__).parent
        env_files = [
            base_path / ".env",
            base_path / ".env.chatwoot",
        ]
        for f in env_files:
            load_env_file(f)
    
    return Config(
        telegram=TelegramConfig(
            token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            allowed_users=_parse_list(os.environ.get("TELEGRAM_ALLOWED_USERS", "")),
        ),
        database=DatabaseConfig(
            dsn=os.environ.get("DATABASE_DSN", "postgresql://aiserver@localhost/avito_parser"),
            pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
            timeout=int(os.environ.get("DB_TIMEOUT", "30")),
        ),
        chatwoot=ChatwootConfig(
            url=os.environ.get("CHATWOOT_URL", "").rstrip("/"),
            token=os.environ.get("CHATWOOT_TOKEN", ""),
            account_id=os.environ.get("CHATWOOT_ACCOUNT_ID", ""),
            whatsapp_inbox=os.environ.get("CHATWOOT_WHATSAPP_INBOX", ""),
            enabled=bool(os.environ.get("CHATWOOT_URL") and os.environ.get("CHATWOOT_TOKEN")),
        ),
        parser=ParserConfig(
            ojp_api_url=os.environ.get("OJP_API_URL", "http://127.0.0.1:8001"),
            avito_result_dir=Path(os.environ.get("AVITO_RESULT_DIR", "/Users/aiserver/OPENCLAW BOT/parser_avito/result")),
            ojp_progress_dir=Path(os.environ.get("OJP_PROGRESS_DIR", "/Users/aiserver/OPENCLAW BOT/ojp_progress")),
        ),
        ai=AIConfig(
            ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            model=os.environ.get("OLLAMA_MODEL", "gemma4:26b"),
        ),
    )


def _parse_list(value: str) -> List[int]:
    """Parse comma-separated list of integers."""
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip().isdigit()]


# Global config instance - initialized on first import
_config: Optional[Config] = None


def get_global_config() -> Config:
    """Get or create global config instance."""
    global _config
    if _config is None:
        _config = get_config()
    return _config


def reset_config() -> None:
    """Reset global config (useful for testing)."""
    global _config
    _config = None