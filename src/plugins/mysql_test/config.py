from pydantic import BaseModel


class Config(BaseModel):
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = "mingyibot"
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_connect_timeout_seconds: int = 5
