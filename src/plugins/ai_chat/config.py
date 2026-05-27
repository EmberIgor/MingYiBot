from pydantic import BaseModel


class Config(BaseModel):
    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""
    aichat_web_search: bool = False
    aichat_default_role: str = "default"
    aichat_history_limit: int = 12
    aichat_roles_path: str = "data/ai_chat_roles.json"
    aichat_session_ttl_minutes: int = 1440
