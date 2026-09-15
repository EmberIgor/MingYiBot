from pydantic import BaseModel
from typing import Literal


class MySQLConfig(BaseModel):
    # Keep the public name for existing plugin configuration subclasses.
    db_backend: Literal["mysql", "postgres"] = "mysql"
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_database: str = "mingyibot"
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_connect_timeout_seconds: int = 5
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = "mingyibot"
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_connect_timeout_seconds: int = 5
