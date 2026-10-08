import os
import json
import urllib.error
import urllib.parse
import urllib.request
from commands import server, finance, accounts

DISCORD_APP_ID = os.environ.get("DISCORD_APPLICATION_ID")
DISCORD_MESSAGE_CONTENT_LIMIT = 2000


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

            # Import erst hier lokal, um zirkuläre Ladekonflikte beim Booten zu verhindern
            import rest_api
            status, resp = rest_api.handle_server_delete({
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

    response_data = None

    if command == "help":
        response_data = {"content": server.get_help_message()}
    elif command == "status":
        response_data = {"content": server.handle_status()}
    elif command == "server":
        if subcommand == "start":
            response_data = {"content": server.handle_start({"options": [{"name": k, "value": v} for k, v in sub_options.items()]})}
        elif subcommand == "stop":
            response_data = {"content": server.handle_stop({"name": sub_options.get("name")})}
        elif subcommand == "reload-files":
            response_data = {"content": server.handle_reload_files(sub_options)}
        elif subcommand == "status":
            response_data = {"content": server.handle_status()}
        elif subcommand == "create":
            response_data = {"content": server.handle_create({"options": [{"name": k, "value": v} for k, v in sub_options.items()]}, caller_id)}
        elif subcommand == "delete":
            del_result = server.handle_delete(sub_options, caller_id)
            response_data = del_result if isinstance(del_result, dict) else {"content": str(del_result)}
        else:
            response_data = {"content": "Unbekannter Server-Befehl."}
    elif command == "whitelist":
        response_data = {"content": accounts.handle_whitelist(subcommand, sub_options, caller_id)}
    elif command == "log":
        response_data = {"content": server.handle_log(data)}
    elif command == "costs":
        response_data = {"content": finance.handle_costs(data, caller_id)}
    elif command == "account":
        response_data = {"content": accounts.handle_account(data, caller_id)}
    elif command == "cash":
        response_data = {"content": accounts.handle_cash(data, caller_id, caller_name)}
    elif command == "addgameaccount":
        response_data = {"content": accounts.handle_addgameaccount(data, caller_id, caller_data)}
    else:
        response_data = {"content": f"Unbekannter Befehl: `/{command}`"}

    return {
        "statusCode": 200,
        "body": {
            "type": 4,
            "data": response_data
        }
    }


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