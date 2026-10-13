import os
import json
import urllib.error
import urllib.parse
import urllib.request
from personal_server_hub.adapters.discord.formatter import format_message
from personal_server_hub.adapters.discord.dispatcher import handle_interaction

DISCORD_MESSAGE_CONTENT_LIMIT = 2000

def split_discord_content(content: str) -> list[str]:
    chunks = []
    while len(content) > DISCORD_MESSAGE_CONTENT_LIMIT:
        limit = DISCORD_MESSAGE_CONTENT_LIMIT
        paragraph_break = content.rfind("\n\n", 0, limit)
        if 0 < paragraph_break and paragraph_break + 2 <= limit:
            split_at = paragraph_break + 2
        else:
            line_break = content.rfind("\n", 0, limit)
            if line_break > 0:
                split_at = line_break + 1
            else:
                whitespace = next(
                    (
                        index
                        for index in range(limit - 1, 0, -1)
                        if content[index].isspace()
                    ),
                    -1,
                )
                split_at = whitespace + 1 if whitespace > 0 else limit
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
            {"content": format_message("async_received")}
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
            "content": format_message("async_error"),
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