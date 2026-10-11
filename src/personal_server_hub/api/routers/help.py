from fastapi import APIRouter

from personal_server_hub.api.schemas.help import HelpResponse
from personal_server_hub.application.help import get_help_message

router = APIRouter()


@router.get("/help", response_model=HelpResponse)
def read_help() -> HelpResponse:
    return HelpResponse(help=get_help_message())
