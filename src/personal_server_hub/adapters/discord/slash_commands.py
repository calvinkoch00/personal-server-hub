from typing import Any


def slash_command_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "body": {
            "type": 4,
            "data": data,
        },
    }
