from pydantic import BaseModel, ConfigDict, Field


class WhitelistAddRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    username: str = Field(min_length=1, max_length=100)
    discord_user_id: str | None = None
    role: str | None = None


class WhitelistRemoveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
    username: str = Field(min_length=1, max_length=100)
    discord_user_id: str | None = None


class WhitelistListRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    game: str = Field(default="minecraft", min_length=1, max_length=50)
    server: str | None = None
    server_name: str | None = None
    server_slug: str | None = None
