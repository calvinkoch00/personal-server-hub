from commands import server, finance, accounts

def handle_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

    if interaction_type != 2:
        return {"statusCode": 400, "body": {"error": "Unsupported interaction type"}}

    data = body.get("data", {})
    command = data.get("name")
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id"))
    caller_name = str(caller_data.get("username", "Admin"))

    if command == "help":
        msg = server.get_help_message()
    elif command == "status":
        msg = server.handle_status()
    elif command == "stop":
        msg = server.handle_stop()
    elif command == "start":
        msg = server.handle_start(data)
    elif command == "log":
        msg = server.handle_log(data)
    elif command == "costs":
        msg = finance.handle_costs(data, caller_id)
    elif command == "account":
        msg = accounts.handle_account(data, caller_id)
    elif command == "cash":
        msg = accounts.handle_cash(data, caller_id, caller_name)
    elif command == "addgameaccount":
        msg = accounts.handle_addgameaccount(data, caller_id, caller_data)
    else:
        msg = f"Unbekannter Befehl: `/{command}`"

    return {
        "statusCode": 200,
        "body": {
            "type": 4,
            "data": {"content": msg}
        }
    }