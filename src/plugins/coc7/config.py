from pydantic import BaseModel


class Config(BaseModel):
    coc7_ai_key: str = ""
    coc7_ai_baseurl: str = ""
    coc7_ai_model: str = ""

    aichat_key: str = ""
    aichat_baseurl: str = ""
    aichat_model: str = ""

    @property
    def effective_ai_key(self) -> str:
        return self.coc7_ai_key or self.aichat_key

    @property
    def effective_ai_baseurl(self) -> str:
        return self.coc7_ai_baseurl or self.aichat_baseurl

    @property
    def effective_ai_model(self) -> str:
        return self.coc7_ai_model or self.aichat_model
