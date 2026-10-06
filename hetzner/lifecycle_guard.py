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
DISCORD_LOG_WEBHOOK = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or DISCORD_STATUS_WEBHOOK
MOUNT_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")
FORCE_SHUTDOWN_FLAG = "/tmp/force_shutdown"


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


def flush_final_shutdown_logs():
    """Sendet die letzten Container-Logs (z. B. Welt-Speicherung, All Chunks Saved) explizit an Discord."""
    if not DISCORD_LOG_WEBHOOK:
        return

    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "-q"],
            capture_output=True,
            text=True
        )
        cids = res.stdout.strip().split()
        if not cids or not cids[0]:
            return

        cid = cids[0]
        logs = subprocess.run(
            ["docker", "logs", "--tail", "25", cid],
            capture_output=True,
            text=True
        )
        raw_text = (logs.stdout or "") + (logs.stderr or "")
        if raw_text.strip():
            chunk = raw_text[-1800:].strip()
            msg = f"📋 **Finale Shutdown-Logs:**\n```asciidoc\n{chunk}\n```"
            requests.post(DISCORD_LOG_WEBHOOK, json={"content": msg}, timeout=5)
    except Exception as e:
        print(f"[GUARD] Finaler Log-Flush fehlgeschlagen: {e}", flush=True)


def execute_shutdown(server_id: str, start_time: float, reason: str = "limit"):
    duration = int(time.time() - start_time)
    
    if reason == "manual":
        send_status(f"🛑 **Server-Stop via Discord ausgeführt.** Server wird beendet (Laufzeit: {duration // 60}m).")
    else:
        send_status(f"🛑 **Laufzeit-Limit erreicht.** Server wird sauber beendet (Laufzeit: {duration // 60}m).")

    # 1. Tracker stoppen (finalisiert Sessions & führt Supabase-Flush aus)
    print("[GUARD] 1. Stoppe Tracker-Dienst (Sessions finalisieren)...", flush=True)
    subprocess.run(["systemctl", "stop", "gameserver-tracker.service"], check=False)

    # 2. Docker Container stoppen (Minecraft flusht Chunks)
    print("[GUARD] 2. Stoppe Docker-Container sauber...", flush=True)
    subprocess.run(["docker", "compose", "-f", f"{MOUNT_DIR}/docker-compose.yml", "stop", "-t", "60"], check=False)
    subprocess.run(["sync"], check=False)

    # 3. Finale Logs aus dem gestoppten Container direkt nach Discord pushen
    print("[GUARD] 3. Sende finale Shutdown-Logs an Discord...", flush=True)
    flush_final_shutdown_logs()

    # 4. Streamer & Control API stoppen
    print("[GUARD] 4. Stoppe Streamer und Control API...", flush=True)
    subprocess.run(["systemctl", "stop", "gameserver-logs.service"], check=False)
    subprocess.run(["systemctl", "stop", "gameserver-control.service"], check=False)

    # 5. Volume sauber aushängen
    print("[GUARD] 5. Unmounte Volume...", flush=True)
    subprocess.run(["umount", "-l", MOUNT_DIR], check=False)

    # 6. Hetzner Server via API löschen
    print(f"[GUARD] 6. Lösche Hetzner Server {server_id}...", flush=True)
    if server_id and HETZNER_API_TOKEN:
        headers = {"Authorization": f"Bearer {HETZNER_API_TOKEN}"}
        try:
            requests.delete(f"https://api.hetzner.cloud/v1/servers/{server_id}", headers=headers, timeout=10)
        except Exception as e:
            print(f"[GUARD] Hetzner Delete Fehler: {e}", flush=True)

    os.system("shutdown -h now")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seconds", type=int, default=300)
    args = parser.parse_args()
    max_seconds = args.max_seconds

    start_time = time.time()
    server_id = get_hetzner_instance_id()
    print(f"[GUARD] Gestartet. Server-ID: {server_id}, Max Seconds: {max_seconds}", flush=True)

    while True:
        # 1. Sofortiger Shutdown-Trigger via Discord /stop
        if os.path.exists(FORCE_SHUTDOWN_FLAG):
            print("[GUARD] Manueller Stop über Discord (/stop) erkannt!", flush=True)
            try:
                os.remove(FORCE_SHUTDOWN_FLAG)
            except Exception:
                pass
            execute_shutdown(server_id, start_time, reason="manual")
            break

        # 2. Timer-Ablauf prüfen
        elapsed = time.time() - start_time
        remaining = max_seconds - elapsed

        if remaining <= 0:
            print("[GUARD] Zeit abgelaufen! Leite automatischen Shutdown ein...", flush=True)
            execute_shutdown(server_id, start_time, reason="limit")
            break

        if int(elapsed) % 60 == 0:
            print(f"[GUARD] Noch {int(remaining)} Sekunden verbleibend.", flush=True)

        time.sleep(1)


if __name__ == "__main__":
    main()