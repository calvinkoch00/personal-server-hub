from pydantic import BaseModel, ConfigDict, Field, field_validator


class GameAccountCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    discord_user_id: str = Field(min_length=1, max_length=20)
    discord_username: str = Field(default="Unknown", min_length=1, max_length=100)
    game: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=1, max_length=100)

    @field_validator("game")
    @classmethod
    def normalize_game(cls, value: str) -> str:
        return value.lower()
