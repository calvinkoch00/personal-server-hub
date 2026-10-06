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
MOUNT_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")


def send_status(msg: str):
    if DISCORD_STATUS_WEBHOOK:
        try:
            requests.post(DISCORD_STATUS_WEBHOOK, json={"content": msg}, timeout=5)
        except Exception:
            pass


def get_hetzner_instance_id() -> str:
    try:
        r = requests.get("http://169.254.169.254/hetzner/v1/metadata/instance-id", timeout=2)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return ""


def execute_shutdown(server_id: str, start_time: float):
    duration = int(time.time() - start_time)
    send_status(f"🛑 **Laufzeit-Limit erreicht.** Server wird sauber beendet (Laufzeit: {duration // 60}m).")

    print("[GUARD] 1. Stoppe Tracker-Dienst (damit offene Sessions finalisiert werden)...")
    subprocess.run(["systemctl", "stop", "gameserver-tracker.service"], check=False)

    print("[GUARD] 2. Stoppe Docker-Container...")
    subprocess.run(["docker", "compose", "-f", f"{MOUNT_DIR}/docker-compose.yml", "stop"], check=False)
    subprocess.run(["sync"], check=False)

    print("[GUARD] 3. Unmounte Volume...")
    subprocess.run(["umount", MOUNT_DIR], check=False)

    print(f"[GUARD] 4. Lösche Hetzner Server {server_id}...")
    if server_id and HETZNER_API_TOKEN:
        headers = {"Authorization": f"Bearer {HETZNER_API_TOKEN}"}
        try:
            requests.delete(f"https://api.hetzner.cloud/v1/servers/{server_id}", headers=headers, timeout=10)
        except Exception as e:
            print(f"[GUARD] Hetzner Delete Fehler: {e}")

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

        if remaining <= 0:
            print("[GUARD] Zeit abgelaufen! Leite Shutdown ein...")
            execute_shutdown(server_id, start_time)
            break

        if int(elapsed) % 60 == 0:
            print(f"[GUARD] Noch {int(remaining)} Sekunden verbleibend.")

        time.sleep(1)


if __name__ == "__main__":
    main()