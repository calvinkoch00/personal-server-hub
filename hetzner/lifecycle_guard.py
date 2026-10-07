import os
import sys
import time
import json
import argparse
import subprocess
import datetime
import requests
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DISCORD_STATUS_WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
DISCORD_LOG_WEBHOOK = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or DISCORD_STATUS_WEBHOOK
MOUNT_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")
FORCE_SHUTDOWN_FLAG = "/tmp/force_shutdown"
SERVER_RUN_CACHE = os.path.join(MOUNT_DIR, "server_run.json")

IDLE_STATE_FILE = "/tmp/last_player_activity"
MAX_IDLE_SECONDS = 3600  # 1 Stunde ohne Spieler

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


def update_server_run_heartbeat(server_id: str, started_at_iso: str):
    """Schreibt den minütlichen Fallback-Heartbeat auf das persistente Volume."""
    if not server_id:
        return
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data = {
        "hetzner_server_id": int(server_id),
        "started_at": started_at_iso,
        "fallback_end_at": now_iso,
        "stopped_at": None,
        "close_reason": None
    }
    tmp_path = SERVER_RUN_CACHE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, SERVER_RUN_CACHE)
    except Exception as e:
        print(f"[GUARD] Heartbeat-Cache Fehler: {e}", flush=True)


def close_server_run_in_supabase(server_id: str, reason: str):
    """Markiert den Serverlauf in Supabase und im lokalen Cache als beendet."""
    if not server_id or not (SUPABASE_URL and SUPABASE_KEY):
        return

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 1. Supabase PATCH
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/fact_server_runs?hetzner_server_id=eq.{server_id}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "stopped_at": now_iso,
        "fallback_end_at": now_iso,
        "close_reason": reason
    }
    try:
        requests.patch(url, json=payload, headers=headers, timeout=5)
        print(f"[GUARD] fact_server_runs erfolgreich geschlossen ({reason}).", flush=True)
    except Exception as e:
        print(f"[GUARD] Fehler beim Schließen von fact_server_runs: {e}", flush=True)

    # 2. Lokalen Cache bereinigen
    try:
        if os.path.exists(SERVER_RUN_CACHE):
            os.remove(SERVER_RUN_CACHE)
    except Exception:
        pass


def flush_final_shutdown_logs():
    """Sendet die letzten Container-Logs explizit an Discord."""
    if not DISCORD_LOG_WEBHOOK:
        return

    try:
        res = subprocess.run(["docker", "ps", "-a", "-q"], capture_output=True, text=True)
        cids = res.stdout.strip().split()
        if not cids or not cids[0]:
            return

        cid = cids[0]
        logs = subprocess.run(["docker", "logs", "--tail", "25", cid], capture_output=True, text=True)
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
    elif reason == "idle":
        send_status(f"💤 **Auto-Idle-Stop:** Seit über 60 Minuten war kein Spieler mehr online. Server wird beendet (Laufzeit: {duration // 60}m).")
    else:
        send_status(f"🛑 **Laufzeit-Limit erreicht.** Server wird sauber beendet (Laufzeit: {duration // 60}m).")

    # 1. Tracker stoppen (finalisiert Sessions & führt Supabase-Flush aus)
    print("[GUARD] 1. Stoppe Tracker-Dienst (Sessions finalisieren)...", flush=True)
    subprocess.run(["systemctl", "stop", "gameserver-tracker.service"], check=False)

    # 2. Server Run in Supabase sauber als beendet eintragen
    print("[GUARD] 2. Schließe Server-Run in Supabase ab...", flush=True)
    close_server_run_in_supabase(server_id, reason)

    # 3. DNS-Record bei automatischem Shutdown via API/Supabase auf 0.0.0.0 zurücksetzen
    print("[GUARD] 3. Setze DNS-Record auf 0.0.0.0 zurück...", flush=True)
    hub_api_url = os.environ.get("HUB_API_URL")
    auth_token = os.environ.get("AUTH_TOKEN")
    current_slug = os.environ.get("SERVER_SLUG")
    if hub_api_url and auth_token and current_slug:
        try:
            requests.post(
                f"{hub_api_url.rstrip('/')}/server/stop",
                json={"name": current_slug},
                headers={"x-auth-token": auth_token, "Content-Type": "application/json"},
                timeout=5
            )
        except Exception as e:
            print(f"[GUARD WARNING] DNS-Reset via API fehlgeschlagen: {e}", flush=True)

    # 4. Docker Container stoppen (Minecraft flusht Chunks)
    print("[GUARD] 4. Stoppe Docker-Container sauber...", flush=True)
    subprocess.run(["docker", "compose", "-f", f"{MOUNT_DIR}/docker-compose.yml", "stop", "-t", "60"], check=False)
    subprocess.run(["sync"], check=False)

    # 5. Finale Logs senden
    print("[GUARD] 5. Sende finale Shutdown-Logs an Discord...", flush=True)
    flush_final_shutdown_logs()

    # 6. Streamer & Control API stoppen
    print("[GUARD] 6. Stoppe Streamer und Control API...", flush=True)
    subprocess.run(["systemctl", "stop", "gameserver-logs.service"], check=False)
    subprocess.run(["systemctl", "stop", "gameserver-control.service"], check=False)

    # 7. Volume unmounten
    print("[GUARD] 7. Unmounte Volume...", flush=True)
    subprocess.run(["umount", "-l", MOUNT_DIR], check=False)

    # 8. Hetzner Server via API löschen
    print(f"[GUARD] 8. Lösche Hetzner Server {server_id}...", flush=True)
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
    started_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    server_id = get_hetzner_instance_id()
    print(f"[GUARD] Gestartet. Server-ID: {server_id}, Max Seconds: {max_seconds}", flush=True)

    # Initialer Heartbeat auf Volume
    update_server_run_heartbeat(server_id, started_at_iso)

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

        # 2. Timer-Ablauf prüfen (max-seconds)
        elapsed = time.time() - start_time
        remaining = max_seconds - elapsed

        if remaining <= 0:
            print("[GUARD] Zeit abgelaufen! Leite automatischen Shutdown ein...", flush=True)
            execute_shutdown(server_id, start_time, reason="limit")
            break

        # 3. 1h-Idle-Check (erst nach 15min Schonfrist nach Boot)
        if elapsed > 900 and os.path.exists(IDLE_STATE_FILE):
            try:
                with open(IDLE_STATE_FILE, "r", encoding="utf-8") as f:
                    last_active = float(f.read().strip())
                idle_seconds = time.time() - last_active

                if idle_seconds >= MAX_IDLE_SECONDS:
                    print(f"[GUARD] Idle-Timeout ({int(idle_seconds)}s ohne Spieler)! Fahre Server herunter...", flush=True)
                    execute_shutdown(server_id, start_time, reason="idle")
                    break
            except Exception:
                pass

        if int(elapsed) % 60 == 0:
            update_server_run_heartbeat(server_id, started_at_iso)
            print(f"[GUARD] Noch {int(remaining)} Sekunden verbleibend.", flush=True)

        time.sleep(1)


if __name__ == "__main__":
    main()