from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from personal_server_hub.api.discord_registry import discord_command 

from personal_server_hub.api.dependencies import require_admin, require_registered
from personal_server_hub.api.schemas.billing import (
    AccountRequest,
    CashRequest,
    CostsRequest,
    ExchangeRateRequest,
)
from personal_server_hub.application.billing import (
    add_cash_payment,
    get_account_balance,
    get_costs_summary,
    get_exchange_rate,
)

router = APIRouter()


@router.post("/exchange-rate", dependencies=[Depends(require_registered)])
def exchange_rate(payload: ExchangeRateRequest) -> JSONResponse:
    status_code, response = get_exchange_rate(payload.model_dump(by_alias=True))
    return JSONResponse(status_code=status_code, content=response)


@router.post("/costs", dependencies=[Depends(require_registered)])
@discord_command("costs", "/costs", method="POST")
def costs_summary(payload: CostsRequest) -> JSONResponse:
    status_code, response = get_costs_summary(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/account", dependencies=[Depends(require_registered)])
@discord_command("account", "/account", method="POST")
def account_balance(payload: AccountRequest) -> JSONResponse:
    status_code, response = get_account_balance(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)


@router.post("/cash", dependencies=[Depends(require_admin)])
@discord_command("cash", "/cash", method="POST")
def cash_payment(payload: CashRequest) -> JSONResponse:
    status_code, response = add_cash_payment(payload.model_dump())
    return JSONResponse(status_code=status_code, content=response)
