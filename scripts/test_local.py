import os
import time
import json
import urllib.request
import urllib.error

# .env manuell einlesen ohne externe Abhängigkeiten
env_vars = {}
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")

if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")

LAMBDA_URL = env_vars.get("LAMBDA_FUNCTION_URL")
AUTH_SECRET = env_vars.get("AUTH_SECRET")
HETZNER_TOKEN = env_vars.get("HETZNER_API_TOKEN")

if not LAMBDA_URL or not AUTH_SECRET or not HETZNER_TOKEN:
    print("Fehler: Bitte prüfe, ob LAMBDA_FUNCTION_URL, AUTH_SECRET und HETZNER_API_TOKEN in .env gesetzt sind.")
    exit(1)

print("1. Starte Server via AWS Lambda...")

req = urllib.request.Request(
    LAMBDA_URL,
    data=json.dumps({"server_type": "cpx32"}).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "x-auth-token": AUTH_SECRET
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("Erfolgreich von Lambda geantwortet:")
        print(json.dumps(data, indent=2))
        server_id = data.get("server_id")
except urllib.error.HTTPError as e:
    print(f"HTTP Fehler bei Lambda: {e.code} - {e.read().decode('utf-8')}")
    exit(1)
except Exception as e:
    print(f"Unerwarteter Fehler: {e}")
    exit(1)

if not server_id:
    print("Keine Server-ID erhalten. Abbruch.")
    exit(1)

print(f"\nServer läuft (ID: {server_id}). Warte 10 Sekunden, damit du ihn kurz in Hetzner sehen kannst...")
time.sleep(10)

print(f"2. Lösche Server {server_id} wieder via Hetzner API...")
del_req = urllib.request.Request(
    f"https://api.hetzner.cloud/v1/servers/{server_id}",
    headers={"Authorization": f"Bearer {HETZNER_TOKEN}"},
    method="DELETE"
)

try:
    with urllib.request.urlopen(del_req) as resp:
        print("Server erfolgreich gelöscht!")
        print("Volume ist wieder freigegeben (Unattached).")
except Exception as e:
    print(f"Fehler beim Löschen des Servers: {e}")