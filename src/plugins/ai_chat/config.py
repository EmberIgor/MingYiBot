from pydantic import Field
from src.common.ai import AIConfig
from src.common.db import MySQLConfig


class Config(AIConfig, MySQLConfig):
    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""
    aichat_web_search: bool = False
    exa_api_key: str = ""
    exa_timeout_seconds: float = Field(default=15.0, gt=0)
    exa_num_results: int = Field(default=5, ge=1, le=10)
    exa_highlight_max_characters: int = Field(default=1200, ge=100, le=10000)
    aichat_default_role: str = "default"
    aichat_history_limit: int = 12
    aichat_roles_path: str = "data/ai_chat_roles.json"
    aichat_session_ttl_minutes: int = 1440
    aichat_memory_enabled: bool = True
    aichat_memory_backend: str = "mysql"
    aichat_memory_path: str = "data/ai_chat_memories.json"
    aichat_memory_max_items: int = 20
    aichat_memory_summary_interval: int = 3

    @property
    def resolved_ai_key(self) -> str:
        return self.aichat_key or self.ai_key

    @property
    def resolved_ai_baseurl(self) -> str:
        return self.aichat_baseurl or self.ai_baseurl

    @property
    def resolved_ai_model(self) -> str:
        return self.aichat_model or self.ai_model
