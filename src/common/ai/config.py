from pydantic import BaseModel


class AIConfig(BaseModel):
    ai_key: str = ""
    ai_baseurl: str = ""
    ai_model: str = ""
