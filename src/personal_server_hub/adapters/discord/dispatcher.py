from fastapi.testclient import TestClient
from personal_server_hub.api.main import app
from personal_server_hub.api.dependencies import internal_headers
from personal_server_hub.api.discord_registry import DISCORD_ROUTE_MAP
from personal_server_hub.adapters.discord.slash_commands import slash_command_response
from personal_server_hub.adapters.discord.formatter import format_server_list, format_message

client = TestClient(app)

def handle_interaction(body: dict, context=None) -> dict:
    interaction_type = body.get("type")

    # 1. Discord Ping/Pong
    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id", "0"))
    caller_name = str(caller_data.get("username", "Admin"))

    # 2. Button Klicks (z. B. Server delete)
    if interaction_type == 3:
        custom_id = body.get("data", {}).get("custom_id", "")
        # ... (Dein exakt bestehender Button-Code aus handle_interaction) ...
        # (Um den Block kurz zu halten: Hier bleibt alles identisch)

    if interaction_type != 2:
        return {"statusCode": 400, "body": {"error": "Unsupported interaction type"}}

    # 3. Slash Commands (Dynamisches Routing)
    data = body.get("data", {})
    command = data.get("name")
    options_list = data.get("options", [])
    
    subcommand = None
    payload_kwargs = {}

    if options_list and options_list[0].get("type") in (1, 2):
        subcommand = options_list[0].get("name")
        for opt in options_list[0].get("options", []):
            payload_kwargs[opt["name"]] = opt.get("value")
    else:
        for opt in options_list:
            payload_kwargs[opt["name"]] = opt.get("value")

    discord_path = f"{command} {subcommand}" if subcommand else command

    payload_kwargs["discord_user_id"] = caller_id
    payload_kwargs["discord_username"] = caller_name
    if "user" not in payload_kwargs:
        payload_kwargs["user"] = "me"
    payload_kwargs["target_uid"] = caller_id
    payload_kwargs["created_by"] = caller_name

    headers = internal_headers(caller_id)
    target_route = DISCORD_ROUTE_MAP.get(discord_path)

    if target_route:
        if target_route["method"] == "GET":
            res = client.get(target_route["path"], params=payload_kwargs, headers=headers)
        else:
            res = client.post(target_route["path"], json=payload_kwargs, headers=headers)
            
        resp = res.json()
        
        if isinstance(resp, dict):
            if "servers" in resp or "data" in resp and isinstance(resp.get("data"), list):
                response_content = format_server_list(resp)
            else:
                response_content = str(resp.get("message") or resp.get("status") or resp.get("payment") or resp.get("help") or resp)
        elif isinstance(resp, list):
            response_content = str(resp)
        else:
            response_content = str(resp)

    elif command == "help":
        response_content = format_message("help")
    else:
        response_content = format_message("unknown_command", command=command)

    return slash_command_response({"content": response_content})