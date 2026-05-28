from pydantic import BaseModel


class Config(BaseModel):
    watchtower_http_api_url: str = "http://watchtower:8080/v1/update"
    watchtower_http_api_token: str = ""
    watchtower_update_image: str = "ghcr.io/emberigor/mingyibot:latest"
    watchtower_http_timeout_seconds: float = 10.0
