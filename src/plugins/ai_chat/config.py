from typing import Literal

from pydantic import BaseModel


class Config(BaseModel):
    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""
    aichat_default_role: str = "default"
    aichat_history_limit: int = 12
    aichat_image_mode: Literal["url", "base64"] = "url"
    aichat_image_max_bytes: int = 5 * 1024 * 1024
    aichat_roles_path: str = "data/ai_chat_roles.json"
    aichat_session_ttl_minutes: int = 1440
