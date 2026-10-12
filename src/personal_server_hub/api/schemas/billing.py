from pydantic import BaseModel, ConfigDict, Field


class ExchangeRateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    base: str | None = None
    from_: str | None = Field(default=None, alias="from")
    target: str | None = None
    to: str | None = None


class CostsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    timeframe: str | None = None
    user: str | None = None


class AccountRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user: str | None = "me"
    target_uid: str | None = None


class CashRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_uid: str = Field(min_length=1, max_length=20)
    amount: float
    currency: str = Field(default="CHF", min_length=1, max_length=10)
    target_currency: str = Field(default="EUR", min_length=1, max_length=10)
    note: str = Field(default="Einzahlung", max_length=255)
    created_by: str = Field(default="Admin", max_length=100)
