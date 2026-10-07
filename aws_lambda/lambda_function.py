import json
import boto3
from services.auth import is_authorized, verify_discord_signature
import discord_api
import rest_api

lambda_client = boto3.client("lambda")

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
        discord_api.execute_async_command(
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
            interaction_res = discord_api.handle_interaction(body_dict, context)
            
            res_body = interaction_res.get("body", {})
            if isinstance(res_body, str):
                res_body = json.loads(res_body)
                
            return json_response(interaction_res.get("statusCode", 200), res_body)
        except Exception as e:
            print(f"[DISCORD ROUTING ERROR] {e}")
            return json_response(500, {"error": str(e)})

    # 2. REST API Entrypoint
    if not is_authorized(headers):
        return json_response(401, {"error": "Unauthorized"})

    raw_path = event.get("rawPath") or event.get("path") or "/"
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body)
        except Exception:
            pass

    try:
        status_code, resp_body = rest_api.route_request(raw_path, body)
        return json_response(status_code, resp_body)
    except Exception as e:
        print(f"[REST ROUTING ERROR] {e}")
        return json_response(500, {"error": str(e)})