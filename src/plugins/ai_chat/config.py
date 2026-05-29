from src.common.ai import AIConfig


class Config(AIConfig):
    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""
    aichat_web_search: bool = False
    aichat_default_role: str = "default"
    aichat_history_limit: int = 12
    aichat_roles_path: str = "data/ai_chat_roles.json"
    aichat_session_ttl_minutes: int = 1440
    aichat_memory_enabled: bool = True
    aichat_memory_backend: str = "mysql"
    aichat_memory_path: str = "data/ai_chat_memories.json"
    aichat_memory_max_items: int = 20
    aichat_memory_summary_interval: int = 3
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = "mingyibot"
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_connect_timeout_seconds: int = 5

    @property
    def resolved_ai_key(self) -> str:
        return self.aichat_key or self.ai_key

    @property
    def resolved_ai_baseurl(self) -> str:
        return self.aichat_baseurl or self.ai_baseurl

    @property
    def resolved_ai_model(self) -> str:
        return self.aichat_model or self.ai_model
