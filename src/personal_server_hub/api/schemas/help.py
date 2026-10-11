from pydantic import BaseModel


class HelpResponse(BaseModel):
    help: str
