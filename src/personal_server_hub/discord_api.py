import os
import json
import urllib.error
import urllib.parse
import urllib.request
from fastapi.testclient import TestClient
from personal_server_hub.api.main import app
from personal_server_hub.api.dependencies import internal_headers
from personal_server_hub.adapters.discord.slash_commands import slash_command_response
from personal_server_hub.adapters.discord.formatter import format_server_list, format_message
from personal_server_hub.application.help import get_help_message

DISCORD_APP_ID = os.environ.get("DISCORD_APPLICATION_ID")
DISCORD_MESSAGE_CONTENT_LIMIT = 2000

client = TestClient(app)


def handle_interaction(body: dict, context=None) -> dict:
    interaction_type = body.get("type")

    # 1. Discord Ping/Pong (Muss in < 10ms beantwortet werden)
    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id", ""))
    caller_name = str(caller_data.get("username", "Admin"))

    # 2. Button Klick (2-stufige Bestätigung für /server delete)
    if interaction_type == 3:
        custom_id = body.get("data", {}).get("custom_id", "")

        if custom_id.startswith("cancel_del:"):
            target_caller = custom_id.split(":")[1]
            if target_caller != caller_id:
                return {
                    "statusCode": 200,
                    "body": {"type": 4, "data": {"content": "⛔ Nur der Ersteller des Befehls kann abbrechen.", "flags": 64}}
                }
            return {
                "statusCode": 200,
                "body": {
                    "type": 7,
                    "data": {"content": "❌ Löschvorgang abgebrochen. Es wurden keine Daten gelöscht.", "components": []}
                }
            }

        if custom_id.startswith("confirm_del:"):
            parts = custom_id.split(":")
            server_slug = parts[1]
            target_caller = parts[2]

            if target_caller != caller_id:
                return {
                    "statusCode": 200,
                    "body": {"type": 4, "data": {"content": "⛔ Du bist nicht berechtigt, diese Aktion zu bestätigen.", "flags": 64}}
                }

            from personal_server_hub.application.servers import handle_server_delete
            status, resp = handle_server_delete({
                "server_name": server_slug,
                "discord_user_id": caller_id
            })

            msg = resp.get("message") if status == 200 else f"❌ {resp.get('error')}"
            return {
                "statusCode": 200,
                "body": {
                    "type": 7,
                    "data": {"content": f"🗑️ {msg}", "components": []}
                }
            }

    if interaction_type != 2:
        return {"statusCode": 400, "body": {"error": "Unsupported interaction type"}}

    # 3. Slash Commands
    data = body.get("data", {})
    command = data.get("name")
    options_list = data.get("options", [])
    subcommand = None
    sub_options = {}

    if options_list and options_list[0].get("type") == 1:
        subcommand = options_list[0].get("name")
        sub_options = {o["name"]: o.get("value") for o in options_list[0].get("options", [])}

    headers = internal_headers(caller_id)
    response_content = ""

    if command == "help":
        response_content = get_help_message()
    elif command == "status":
        res = client.get("/servers", headers=headers)
        resp = res.json()
        response_content = format_server_list(resp)
    elif command == "server":
        if subcommand == "start":
            res = client.post("/start", json=sub_options, headers=headers)
            resp = res.json()
            response_content = resp.get("message") or resp.get("status") or str(resp)
        elif subcommand == "stop":
            res = client.post("/stop", json=sub_options, headers=headers)
            resp = res.json()
            response_content = resp.get("message") or resp.get("status") or str(resp)
        elif subcommand == "reload-files":
            res = client.post("/server/reload-files", json=sub_options, headers=headers)
            resp = res.json()
            response_content = resp.get("message") or resp.get("status") or str(resp)
        elif subcommand == "status":
            res = client.get("/servers", headers=headers)
            resp = res.json()
            response_content = format_server_list(resp)
        elif subcommand == "create":
            res = client.post("/server/create", json={**sub_options, "discord_user_id": caller_id}, headers=headers)
            resp = res.json()
            response_content = resp.get("message") or resp.get("status") or str(resp)
        elif subcommand == "delete":
            res = client.post("/server/delete", json={**sub_options, "discord_user_id": caller_id}, headers=headers)
            resp = res.json()
            response_content = resp.get("message") or resp.get("status") or str(resp)
        else:
            response_content = format_message("server_unknown", "Unbekannter Server-Befehl.")
    elif command == "whitelist":
        res = client.post(f"/whitelist/{subcommand}", json={**sub_options, "discord_user_id": caller_id}, headers=headers)
        resp = res.json()
        response_content = str(resp.get("status") or resp.get("entries") or resp)
    elif command == "log":
        res = client.post("/log", json=data, headers=headers)
        resp = res.json()
        response_content = str(resp.get("status") or resp)
    elif command == "costs":
        res = client.post("/costs", json={**sub_options, "discord_user_id": caller_id}, headers=headers)
        resp = res.json()
        response_content = str(resp.get("rows") or resp)
    elif command == "account":
        res = client.post("/account", json={"user": sub_options.get("user", "me"), "target_uid": caller_id}, headers=headers)
        resp = res.json()
        response_content = str(resp)
    elif command == "cash":
        res = client.post("/cash", json={**sub_options, "created_by": caller_name}, headers=headers)
        resp = res.json()
        response_content = str(resp.get("payment") or resp)
    elif command == "addgameaccount":
        game_options = {o["name"]: o.get("value") for o in data.get("options", [])}
        res = client.post("/game-accounts", json={**game_options, "discord_user_id": caller_id, "discord_username": caller_data.get("username")}, headers=headers)
        resp = res.json()
        response_content = resp.get("message") or resp.get("status") or str(resp)
    else:
        response_content = format_message("unknown_command", f"Unbekannter Befehl: `/{command}`", command=command)

    return slash_command_response({"content": response_content})


def split_discord_content(content: str) -> list[str]:
    chunks = []
    while len(content) > DISCORD_MESSAGE_CONTENT_LIMIT:
        split_at = content.rfind("\n", 0, DISCORD_MESSAGE_CONTENT_LIMIT)
        if split_at < 0:
            split_at = content.rfind(" ", 0, DISCORD_MESSAGE_CONTENT_LIMIT)
        split_at = split_at + 1 if split_at > 0 else DISCORD_MESSAGE_CONTENT_LIMIT
        chunks.append(content[:split_at])
        content = content[split_at:]

    if content or not chunks:
        chunks.append(content)
    return chunks


def execute_async_command(command_payload: dict, token: str, app_id: str) -> None:
    app_id_path = urllib.parse.quote(str(app_id), safe="")
    token_path = urllib.parse.quote(token, safe="")
    original_response_url = (
        f"https://discord.com/api/v10/webhooks/{app_id_path}/"
        f"{token_path}/messages/@original"
    )
    followup_url = f"https://discord.com/api/v10/webhooks/{app_id_path}/{token_path}"

    def send_webhook_request(url: str, method: str, data: dict) -> None:
        request = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/calvinkoch00/personal-server-hub, 1.0)"
            },
            method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            print(f"[DISCORD FOLLOW-UP ERROR] HTTP {e.code}: {error_body}")
        except Exception as e:
            print(f"[DISCORD FOLLOW-UP ERROR] {e}")

    is_slash_command = command_payload.get("type") == 2
    if is_slash_command:
        send_webhook_request(
            original_response_url,
            "PATCH",
            {"content": "✅ Befehl empfangen – ich versuche ihn auszuführen…"}
        )

    try:
        interaction_res = handle_interaction(command_payload)
        status_code = interaction_res.get("statusCode", 500)
        response_body = interaction_res.get("body", {})
        if isinstance(response_body, str):
            response_body = json.loads(response_body)

        if status_code >= 400:
            raise RuntimeError(
                f"Discord command handler returned HTTP {status_code}: {response_body}"
            )

        response_type = response_body.get("type")
        response_data = response_body.get("data")
        if response_type not in (4, 7) or not isinstance(response_data, dict):
            raise RuntimeError(f"Unexpected Discord command response: {response_body}")
    except Exception as e:
        print(f"[DISCORD COMMAND ERROR] {e}")
        response_type = 4
        response_data = {
            "content": "❌ Der Befehl konnte nicht ausgeführt werden. Bitte prüfe die Server-Logs.",
            "flags": 64
        }

    content = response_data.get("content")
    if isinstance(content, str):
        content_chunks = split_discord_content(content)
        first_response_data = dict(response_data)
        first_response_data["content"] = content_chunks[0]
    else:
        content_chunks = []
        first_response_data = response_data

    if command_payload.get("type") == 3 and response_type == 7:
        send_webhook_request(original_response_url, "PATCH", first_response_data)
    elif command_payload.get("type") == 3:
        send_webhook_request(followup_url, "POST", first_response_data)
    else:
        send_webhook_request(original_response_url, "PATCH", first_response_data)

    for content_chunk in content_chunks[1:]:
        send_webhook_request(followup_url, "POST", {"content": content_chunk})