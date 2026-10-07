import os
import json
from commands import server, finance, accounts

DISCORD_APP_ID = os.environ.get("DISCORD_APPLICATION_ID")

def handle_interaction(body: dict) -> dict:
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