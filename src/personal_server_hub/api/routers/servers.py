from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from personal_server_hub.api.dependencies import require_registered
from personal_server_hub.api.schemas.servers import (
    ServerCreateRequest,
    ServerDeleteRequest,
    ServerStartRequest,
    ServerStopRequest,
)
from personal_server_hub.application.servers import (
    handle_server_create,
    handle_server_delete,
    handle_servers,
    handle_start,
    handle_stop,
)

router = APIRouter()


@router.post("/server/start", dependencies=[Depends(require_registered)])
@router.post("/start", dependencies=[Depends(require_registered)])
def start_server(payload: ServerStartRequest) -> JSONResponse:
    status_code, response = handle_start(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/stop", dependencies=[Depends(require_registered)])
@router.post("/stop", dependencies=[Depends(require_registered)])
def stop_server(payload: ServerStopRequest) -> JSONResponse:
    status_code, response = handle_stop(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/create", dependencies=[Depends(require_registered)])
def create_server(payload: ServerCreateRequest) -> JSONResponse:
    status_code, response = handle_server_create(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/delete", dependencies=[Depends(require_registered)])
def delete_server(payload: ServerDeleteRequest) -> JSONResponse:
    status_code, response = handle_server_delete(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.get("/servers", dependencies=[Depends(require_registered)])
def list_servers() -> JSONResponse:
    status_code, response = handle_servers()
    return JSONResponse(status_code=status_code, content=response)
