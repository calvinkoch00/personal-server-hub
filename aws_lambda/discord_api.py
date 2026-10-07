import os
import json
import urllib.request
import rest_api
from commands import server, finance, accounts

DISCORD_APP_ID = os.environ.get("DISCORD_APPLICATION_ID")

def send_followup(token: str, content: str | dict, app_id: str | None = None):
    resolved_app_id = app_id or os.environ.get("DISCORD_APPLICATION_ID")
    if not resolved_app_id or not token:
        print(f"[DISCORD FOLLOWUP ERROR] Fehlende App-ID ({resolved_app_id}) oder Token ({bool(token)})")
        return

    url = f"https://discord.com/api/v10/webhooks/{resolved_app_id}/{token}/messages/@original"
    
    if isinstance(content, dict):
        payload = content
    else:
        payload = {"content": str(content)}

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/calvinkoch00/personal-server-hub, 1.0)"
        },
        method="PATCH"
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            print(f"[DISCORD FOLLOWUP] Erfolgreich zugestellt: Status {resp.status}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        print(f"[DISCORD FOLLOWUP HTTP ERROR] Code {e.code}: {err_body}")
    except Exception as e:
        print(f"[DISCORD FOLLOWUP ERROR] Fehler: {e}")

def handle_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    # 1. Ping-Pong
    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

    interaction_token = body.get("token")
    app_id = body.get("application_id") or DISCORD_APP_ID
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id"))
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

    # Zeitaufwendige Server-Befehle via Background-Followup ausführen
    if command == "server" and subcommand in ["start", "stop", "reload-files", "create"]:
        res_text = "Befehl ausgeführt."
        if subcommand == "start":
            res_text = server.handle_start({"options": [{"name": k, "value": v} for k, v in sub_options.items()]})
        elif subcommand == "stop":
            res_text = server.handle_stop({"name": sub_options.get("name")})
        elif subcommand == "reload-files":
            res_text = server.handle_reload_files(sub_options)
        elif subcommand == "create":
            res_text = server.handle_create({"options": [{"name": k, "value": v} for k, v in sub_options.items()]}, caller_id)

        # Erst Followup senden
        send_followup(interaction_token, res_text, app_id)

        return {
            "statusCode": 200,
            "body": {"type": 5}
        }

    # Sofortige Befehle
    response_data = None

    if command == "help":
        response_data = {"content": server.get_help_message()}
    elif command == "status":
        response_data = {"content": server.handle_status()}
    elif command == "server":
        if subcommand == "status":
            response_data = {"content": server.handle_status()}
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