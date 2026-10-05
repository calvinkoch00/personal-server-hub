import os

def is_authorized(headers: dict) -> bool:
    auth_secret = os.environ.get("AUTH_SECRET", "")
    if not headers or not auth_secret:
        return False

    incoming_secret = (
        headers.get("x-auth-token")
        or headers.get("X-Auth-Token")
        or headers.get("authorization", "").replace("Bearer ", "")
    )
    return incoming_secret == auth_secret