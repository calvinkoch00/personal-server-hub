import json
import os
import urllib.request
import urllib.error

# Umgebungsvariablen aus der AWS Lambda Konfiguration
HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN")
VOLUME_ID = os.environ.get("VOLUME_ID")
LOCATION = os.environ.get("LOCATION", "nbg1")
AUTH_SECRET = os.environ.get("AUTH_SECRET")

# Cloud-Init-Skript: Mountet das persistente Volume und startet Docker Compose
CLOUD_INIT_SCRIPT = f"""#cloud-config
runcmd:
  - mkdir -p /mnt/gamespeicher
  - mount -o discard,defaults /dev/disk/by-id/scsi-0HC_Volume_{VOLUME_ID} /mnt/gamespeicher
  - cd /mnt/gamespeicher && docker compose up -d
"""

def lambda_handler(event, context):
    headers = event.get("headers", {}) or {}

    # 1. Header-Authentifizierung prüfen
    incoming_secret = headers.get("x-auth-token") or headers.get("X-Auth-Token")
    if incoming_secret != AUTH_SECRET:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Unauthorized: Ungueltiges oder fehlendes Auth-Token"})
        }

    # 2. HTTP-Body auswerten (Servertyp dynamisch wählbar)
    body = {}
    raw_body = event.get("body")
    if raw_body:
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            pass

    server_type = body.get("server_type", "cpx32")

    # 3. Payload für Hetzner Cloud API zusammenbauen
    payload = {
        "name": "minecraft-ondemand",
        "server_type": server_type,
        "image": "ubuntu-24.04",
        "location": LOCATION,
        "start_after_create": True,
        "volumes": [int(VOLUME_ID)],
        "user_data": CLOUD_INIT_SCRIPT
    }

    req = urllib.request.Request(
        "https://api.hetzner.cloud/v1/servers",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {HETZNER_API_TOKEN}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            server = res_body.get("server", {})
            server_id = server.get("id")
            public_ip = server.get("public_net", {}).get("ipv4", {}).get("ip")

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "message": "Server erfolgreich provisioniert",
                    "server_id": server_id,
                    "ip": public_ip,
                    "server_type": server_type
                })
            }
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        return {
            "statusCode": e.code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Hetzner API Fehler", "details": error_msg})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)})
        }