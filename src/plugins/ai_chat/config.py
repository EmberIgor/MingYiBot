from pydantic import Field
from src.common.ai import AIConfig


class Config(AIConfig):
    hermes_baseurl: str = ""
    hermes_key: str = ""
    hermes_model: str = "mingyi-public"
    hermes_request_timeout_seconds: float = Field(default=120.0, gt=0)
    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""
    aichat_web_search: bool = False
    exa_api_key: str = ""
    exa_timeout_seconds: float = Field(default=15.0, gt=0)
    exa_num_results: int = Field(default=5, ge=1, le=10)
    exa_highlight_max_characters: int = Field(default=1200, ge=100, le=10000)
    aichat_history_limit: int = 12
    aichat_session_ttl_minutes: int = 1440
    aichat_max_concurrency: int = Field(default=5, ge=1, le=100)
    aichat_request_timeout_seconds: float = Field(default=60.0, gt=0)

    @property
    def resolved_ai_key(self) -> str:
        return self.aichat_key or self.ai_key

    @property
    def resolved_ai_baseurl(self) -> str:
        return self.aichat_baseurl or self.ai_baseurl

    @property
    def resolved_ai_model(self) -> str:
        return self.aichat_model or self.ai_model
