from fastapi import APIRouter
from fastapi.responses import JSONResponse

from personal_server_hub.api.schemas.users import UserRegisterRequest
from personal_server_hub.application.users import get_user, register_user

router = APIRouter()


@router.post("/users/register")
def create_user(payload: UserRegisterRequest) -> JSONResponse:
    status_code, response = register_user(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.get("/users/{discord_user_id}")
def read_user(discord_user_id: str) -> JSONResponse:
    status_code, response = get_user(discord_user_id)
    return JSONResponse(status_code=status_code, content=response)
