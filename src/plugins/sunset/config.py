from typing import Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    sunset_api_url: str = "https://sunsetbot.top/"
    sunset_default_city: str = "北京"
    sunset_model: Literal["GFS", "EC"] = "GFS"
    sunset_timeout_seconds: float = 10.0
    sunset_notify_enabled: bool = True
    sunset_notify_times: list[str] = Field(default_factory=lambda: ["09:00", "21:00"])
    sunset_notify_threshold: str = "中烧"
    sunset_owner_ids: list[str] = Field(default_factory=list)
