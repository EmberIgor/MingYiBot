from pydantic import BaseModel


class Config(BaseModel):
    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""
    aichat_default_role: str = "default"
    aichat_history_limit: int = 12
    aichat_roles_path: str = "data/ai_chat_roles.json"
