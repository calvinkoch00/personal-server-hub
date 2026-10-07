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

    options_list = data.get("options", [])
    subcommand = None
    sub_options = {}
    if options_list and options_list[0].get("type") == 1:
        subcommand = options_list[0].get("name")
        sub_options = {o["name"]: o.get("value") for o in options_list[0].get("options", [])}

    if command == "help":
        msg = server.get_help_message()
    elif command == "status":
        msg = server.handle_status()
    elif command == "stop":
        msg = server.handle_stop()
    elif command == "start":
        msg = server.handle_start(data)
    elif command == "server":
        if subcommand == "start":
            msg = server.handle_start({"options": [{"name": k, "value": v} for k, v in sub_options.items()]})
        elif subcommand == "stop":
            msg = server.handle_stop({"name": sub_options.get("name")})
        elif subcommand == "status":
            msg = server.handle_status()
        elif subcommand == "create":
            msg = server.handle_create({"options": [{"name": k, "value": v} for k, v in sub_options.items()]}, caller_id)
        elif subcommand == "delete":
            msg = server.handle_delete({"options": [{"name": k, "value": v} for k, v in sub_options.items()]}, caller_id)
        else:
            msg = "Unbekannter Server-Befehl."
    elif command == "whitelist":
        msg = accounts.handle_whitelist(subcommand, sub_options, caller_id)
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