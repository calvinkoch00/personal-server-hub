from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from personal_server_hub.api.dependencies import require_registered
from personal_server_hub.api.schemas.whitelist import (
    WhitelistAddRequest,
    WhitelistListRequest,
    WhitelistRemoveRequest,
)
from personal_server_hub.application.whitelist import (
    add_whitelist,
    list_whitelist,
    remove_whitelist,
)

router = APIRouter()


@router.post("/whitelist/add", dependencies=[Depends(require_registered)])
def whitelist_add(payload: WhitelistAddRequest) -> JSONResponse:
    status_code, response = add_whitelist(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/whitelist/remove", dependencies=[Depends(require_registered)])
def whitelist_remove(payload: WhitelistRemoveRequest) -> JSONResponse:
    status_code, response = remove_whitelist(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/whitelist/list", dependencies=[Depends(require_registered)])
def whitelist_list(payload: WhitelistListRequest) -> JSONResponse:
    status_code, response = list_whitelist(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)
