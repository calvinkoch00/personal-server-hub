from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from personal_server_hub.api.discord_registry import discord_command

from personal_server_hub.api.dependencies import require_registered
from personal_server_hub.api.schemas.servers import (
    ServerCreateRequest,
    ServerDeleteRequest,
    ServerLogRequest,
    ServerReloadFilesRequest,
    ServerStartRequest,
    ServerStopRequest,
)
from personal_server_hub.application.servers import (
    handle_log,
    handle_server_create,
    handle_server_delete,
    handle_server_reload_files,
    handle_servers,
    handle_start,
    handle_stop,
)

router = APIRouter()


@router.post("/server/start", dependencies=[Depends(require_registered)])
@discord_command("server start", "/server/start", method="POST")
def start_server(payload: ServerStartRequest) -> JSONResponse:
    status_code, response = handle_start(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/stop", dependencies=[Depends(require_registered)])
@discord_command("server stop", "/server/stop", method="POST")
def stop_server(payload: ServerStopRequest) -> JSONResponse:
    status_code, response = handle_stop(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/create", dependencies=[Depends(require_registered)])
@discord_command("server create", "/server/create", method="POST")
def create_server(payload: ServerCreateRequest) -> JSONResponse:
    status_code, response = handle_server_create(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/delete", dependencies=[Depends(require_registered)])
@discord_command("server delete", "/server/delete", method="POST")
def delete_server(payload: ServerDeleteRequest) -> JSONResponse:
    status_code, response = handle_server_delete(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.get("/servers", dependencies=[Depends(require_registered)])
@discord_command("server status", "/servers", method="GET")
def list_servers() -> JSONResponse:
    status_code, response = handle_servers()
    return JSONResponse(status_code=status_code, content=response)



@router.post("/log", dependencies=[Depends(require_registered)])
@discord_command("log", "/log", method="POST")
def set_server_log(payload: ServerLogRequest) -> JSONResponse:
    status_code, response = handle_log(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/server/reload-files", dependencies=[Depends(require_registered)])
@discord_command("server reload files", "/server/reload-files", method="POST")
def reload_server_files(payload: ServerReloadFilesRequest) -> JSONResponse:
    status_code, response = handle_server_reload_files(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)