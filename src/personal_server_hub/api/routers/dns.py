from fastapi import APIRouter
from fastapi.responses import JSONResponse

from personal_server_hub.application.dns import list_dns_records, sync_dns_records

router = APIRouter()


@router.get("/dns/records")
def read_dns_records() -> JSONResponse:
    status_code, response = list_dns_records()
    return JSONResponse(status_code=status_code, content=response)


@router.post("/dns/sync")
def sync_dns() -> JSONResponse:
    status_code, response = sync_dns_records()
    return JSONResponse(status_code=status_code, content=response)
