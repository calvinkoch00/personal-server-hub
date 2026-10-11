from pydantic import BaseModel, ConfigDict, Field


class UserRegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    discord_user_id: str = Field(min_length=1, max_length=20)
    discord_username: str = Field(default="Unknown", min_length=1, max_length=100)
