from typing import Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    dailynews_enabled: bool = True
    dailynews_time: str = "08:30"
    dailynews_latest_time: str = "10:10"
    dailynews_retry_interval_minutes: int = 10
    dailynews_require_today: bool = True
    dailynews_api_url: str = "https://60s.viki.moe/v2/60s"
    dailynews_image_encoding: Literal["image", "image-proxy"] = "image"
    dailynews_group_mode: Literal["blacklist", "whitelist"] = "blacklist"
    dailynews_group_ids: list[int] = Field(default_factory=list)
