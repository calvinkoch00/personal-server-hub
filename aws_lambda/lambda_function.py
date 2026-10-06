import json
from services.auth import is_authorized, verify_discord_signature
import discord_api
from rest_api import handle_rest_request


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
    headers = event.get("headers", {}) or {}
    raw_body = event.get("body", "") or ""

    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod", "GET")
    )
    if http_method == "OPTIONS":
        return json_response(200, {"message": "CORS OK"})

    # 1. Discord Webhook Route
    if "x-signature-ed25519" in headers or "X-Signature-Ed25519" in headers:
        if not verify_discord_signature(headers, raw_body):
            return json_response(401, {"error": "Invalid Discord Signature"})
        try:
            interaction_res = discord_api.handle_interaction(json.loads(raw_body))
            return json_response(interaction_res["statusCode"], interaction_res["body"])
        except Exception as e:
            return json_response(500, {"error": str(e)})

    # 2. REST API Route (Token Auth)
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
        status_code, response_data = handle_rest_request(raw_path, body)
        return json_response(status_code, response_data)
    except Exception as e:
        return json_response(500, {"error": str(e)})