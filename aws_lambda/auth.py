import os
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

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

def verify_discord_signature(headers: dict, raw_body: str) -> bool:
    public_key = os.environ.get("DISCORD_PUBLIC_KEY", "")
    if not public_key:
        return False

    signature = headers.get("x-signature-ed25519") or headers.get("X-Signature-Ed25519")
    timestamp = headers.get("x-signature-timestamp") or headers.get("X-Signature-Timestamp")

    if not signature or not timestamp or not raw_body:
        return False

    try:
        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(f"{timestamp}{raw_body}".encode("utf-8"), bytes.fromhex(signature))
        return True
    except (BadSignatureError, Exception):
        return False