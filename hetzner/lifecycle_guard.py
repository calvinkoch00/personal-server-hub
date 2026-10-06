import os
import sys
import time
import argparse
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN")
DISCORD_STATUS_WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
MOUNT_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")

def send_status(msg: str):
    if DISCORD_STATUS_WEBHOOK:
        try:
            requests.post(DISCORD_STATUS_WEBHOOK, json={"content": msg}, timeout=5)
        except Exception:
            pass

def get_hetzner_instance_id() -> str:
    """Ermittelt die eigene Hetzner Server-ID über den Metadaten-Endpunkt."""
    try:
        r = requests.get("http://169.254.169.254/hetzner/v1/metadata/instance-id", timeout=2)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return ""

def log_session_to_supabase(start_time: float, total_seconds: int):
    if not (SUPABASE_URL and SUPABASE_KEY):
        print("[GUARD] Supabase Credentials fehlen, überspringe Logging.")
        return

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/server_sessions"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    payload = {
        "start_time": int(start_time),
        "duration_seconds": total_seconds,
        "game": os.environ.get("GAME_NAME", "minecraft"),
        "created_at": "now()"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=5)
        print(f"[GUARD] Supabase Status: {r.status_code}")
    except Exception as e:
        print(f"[GUARD] Supabase Fehler: {e}")

def execute_shutdown(server_id: str, start_time: float):
    duration = int(time.time() - start_time)
    send_status(f"🛑 **Laufzeit-Limit erreicht.** Server wird sauber beendet (Laufzeit: {duration // 60}m).")

    print("[GUARD] 1. Stoppe Docker-Container...")
    subprocess.run(["docker", "compose", "-f", f"{MOUNT_DIR}/docker-compose.yml", "stop"], check=False)

    print("[GUARD] 2. Logge Session zu Supabase...")
    log_session_to_supabase(start_time, duration)

    print("[GUARD] 3. Unmounte Volume...")
    subprocess.run(["umount", MOUNT_DIR], check=False)

    print(f"[GUARD] 4. Lösche Hetzner Server {server_id}...")
    if server_id and HETZNER_API_TOKEN:
        headers = {"Authorization": f"Bearer {HETZNER_API_TOKEN}"}
        requests.delete(f"https://api.hetzner.cloud/v1/servers/{server_id}", headers=headers, timeout=10)

    # Lokaler Fallback-Shutdown falls API verzögert
    os.system("shutdown -h now")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seconds", type=int, default=300)
    args = parser.parse_args()

    max_seconds = args.max_seconds
    start_time = time.time()
    server_id = get_hetzner_instance_id()

    print(f"[GUARD] Gestartet. Server-ID: {server_id}, Max Seconds: {max_seconds}")

    while True:
        elapsed = time.time() - start_time
        remaining = max_seconds - elapsed

        # Prüfe ob Zeit abgelaufen ODER /stop getriggert wurde
        if remaining <= 0 or os.path.exists("/tmp/force_shutdown"):
            if os.path.exists("/tmp/force_shutdown"):
                print("[GUARD] Manueller Stop über /stop empfangen! Fahre herunter...")
            else:
                print("[GUARD] Zeit abgelaufen! Fahre herunter...")

            execute_shutdown(server_id, start_time)
            break

        time.sleep(1)

if __name__ == "__main__":
    main()