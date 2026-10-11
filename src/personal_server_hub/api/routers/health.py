from fastapi import APIRouter

router = APIRouter()

# GET endpoint to get the Health of our API
@router.get("/health")
def health_check() -> dict[str, str]:   #runs function "health_check" when endpint is called
                                        # -> dict[str, str] indicates the return type of the function is a dictionary with string keys and string values
    return {"status": "ok"}             # always returns "{"status": "ok"}"