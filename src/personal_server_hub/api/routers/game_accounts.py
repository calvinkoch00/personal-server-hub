from fastapi import APIRouter
from fastapi.responses import JSONResponse

from personal_server_hub.api.schemas.game_accounts import GameAccountCreateRequest
from personal_server_hub.application.game_accounts import add_game_account

router = APIRouter()


@router.post("/game-accounts")
def create_game_account(payload: GameAccountCreateRequest) -> JSONResponse:
    status_code, response = add_game_account(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)
