from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerStartRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    name: str | None = None
    duration: str | None = "5m"
    server_type: str | None = None
    log: str | None = None
    logging: str | None = None


class ServerStopRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    server_id: str | None = None
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    name: str | None = None


class ServerCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    name: str | None = None
    discord_user_id: str | None = None
    server_type: str | None = "cpx32"
    custom_subdomain: str | None = None
    subdomain: str | None = None

    @field_validator("server", "server_name", "server_slug", "name", mode="after")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is not None:
            import re
            cleaned = value.strip().lower()
            if cleaned and not re.match(r"^[a-z0-9_-]+$", cleaned):
                raise ValueError("Server name must contain only lowercase letters, numbers, underscores, and hyphens.")
        return value


class ServerDeleteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    name: str | None = None
    discord_user_id: str | None = None


class ServerLogRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    name: str | None = None
    mode: str | None = "game"
    logging: str | None = None


class ServerReloadFilesRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    name: str | None = None

