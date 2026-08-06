from pydantic import BaseModel, Field


class Config(BaseModel):
    vv_api_url: str = "https://vvapi.cicada000.work"
    vv_image_base_url: str = "https://vv.noxylva.org"
    vv_timeout_seconds: float = Field(default=10.0, gt=0)
    vv_cooldown_seconds: float = Field(default=10.0, gt=0)
    vv_index_cache_seconds: float = Field(default=3600.0, gt=0)
