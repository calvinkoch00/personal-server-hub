from fastapi import APIRouter
from fastapi.responses import JSONResponse

from personal_server_hub.api.schemas.users import UserRegisterRequest
from personal_server_hub.application.users import register_user

router = APIRouter()


@router.post("/users/register")
def create_user(payload: UserRegisterRequest) -> JSONResponse:
    status_code, response = register_user(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)
