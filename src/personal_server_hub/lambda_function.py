import os
import json
import boto3
from mangum import Mangum
from personal_server_hub.runtime_secrets import load_runtime_secrets

# Application modules read some settings at import time.
load_runtime_secrets()

from personal_server_hub.security import is_authorized, verify_discord_signature
from personal_server_hub.api.main import app
from personal_server_hub.adapters.discord.formatter import format_message
from personal_server_hub.adapters.discord.dispatcher import handle_interaction
from personal_server_hub.adapters.discord.webhook import execute_async_command

AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
asgi_handler = Mangum(app)

def json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*"
        },
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    # 0. Asynchroner Worker-Eingang
    if event.get("async_worker"):
        print("[ASYNC WORKER] Starte Hintergrund-Job...")
        execute_async_command(
            command_payload=event.get("command_payload"),
            token=event.get("token"),
            app_id=event.get("app_id")
        )
        return json_response(200, {"status": "done"})

    headers = event.get("headers", {}) or {}
    raw_body = event.get("body", "") or ""

    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod", "GET")
    )
    if http_method == "OPTIONS":
        return json_response(200, {"message": "CORS OK"})

    # Header-Keys vereinheitlichen (lowercase)
    norm_headers = {k.lower(): v for k, v in headers.items()}

    # 1. Discord Webhook Entrypoint
    if "x-signature-ed25519" in norm_headers:
        if not verify_discord_signature(headers, raw_body):
            print("[AUTH ERROR] Discord Signatur ungültig")
            return json_response(401, {"error": "Invalid Discord Signature"})
        try:
            body_dict = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

            interaction_type = body_dict.get("type")
            if interaction_type == 1:
                return json_response(200, {"type": 1})

            if interaction_type in (2, 3):
                token = body_dict.get("token")
                app_id = body_dict.get("application_id") or handle_interaction.DISCORD_APP_ID
                function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
                if not token or not app_id or not function_name:
                    raise RuntimeError(
                        "Discord interaction token, application ID oder Lambda-Funktionsname fehlt"
                    )

                worker_event = {
                    "async_worker": True,
                    "command_payload": body_dict,
                    "token": token,
                    "app_id": app_id
                }
                invoke_res = lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType="Event",
                    Payload=json.dumps(worker_event).encode("utf-8")
                )
                if invoke_res.get("StatusCode") != 202:
                    raise RuntimeError(
                        f"Asynchroner Discord-Worker konnte nicht gestartet werden: {invoke_res}"
                    )

                # Discord-Komponenten benötigen eine Deferred Update-Antwort (Typ 6);
                # Slash Commands eine Deferred Channel Message (Typ 5).
                ack_type = 6 if interaction_type == 3 else 5
                return json_response(200, {"type": ack_type})

            interaction_res = handle_interaction(body_dict, context)
            res_body = interaction_res.get("body", {})
            if isinstance(res_body, str):
                res_body = json.loads(res_body)
            return json_response(interaction_res.get("statusCode", 200), res_body)
        except Exception as e:
            print(f"[DISCORD ROUTING ERROR] {e}")
            return json_response(500, {"error": str(e)})

    # 2. REST API Entrypoint
    from personal_server_hub.api.dependencies import INTERNAL_TOKEN, INTERNAL_TOKEN_HEADER, DISCORD_USER_HEADER
    import hmac

    internal_token = norm_headers.get(INTERNAL_TOKEN_HEADER, "")
    discord_uid = norm_headers.get(DISCORD_USER_HEADER, "").strip()
    is_internal_discord_call = bool(
        discord_uid
        and internal_token
        and hmac.compare_digest(internal_token, INTERNAL_TOKEN)
    )

    if not is_internal_discord_call and not is_authorized(headers):
        return json_response(401, {"error": "Unauthorized"})

    return asgi_handler(event, context)