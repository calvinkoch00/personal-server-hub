import os
import sys
import time
import re
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

STATUS_WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
LOG_WEBHOOK = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or STATUS_WEBHOOK
CONFIG_FILE = "/tmp/discord_log_mode"

SERVER_ID = os.environ.get("SERVER_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

WL_ADD_REGEX = re.compile(r"Added ([a-zA-Z0-9_]{3,16}) to the whitelist", re.IGNORECASE)
WL_REM_REGEX = re.compile(r"Removed ([a-zA-Z0-9_]{3,16}) from the whitelist", re.IGNORECASE)
OP_ADD_REGEX = re.compile(r"Made ([a-zA-Z0-9_]{3,16}) a server operator", re.IGNORECASE)
OP_REM_REGEX = re.compile(r"Made ([a-zA-Z0-9_]{3,16}) no longer a server operator", re.IGNORECASE)

def _supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

def get_account_id_by_username(username: str) -> tuple[str | None, str | None]:
    """Sucht account_id und discord_user_id anhand des Ingame-Namens in Supabase."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None, None
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/dim_game_accounts?game=eq.minecraft&ingame_username=ilike.{username}&select=id,discord_user_id"
    try:
        r = requests.get(url, headers=_supabase_headers(), timeout=5)
        if r.status_code == 200 and r.json():
            row = r.json()[0]
            return row.get("id"), str(row.get("discord_user_id"))
    except Exception as e:
        print(f"[LOG_STREAMER] Account Lookup Fehler: {e}", flush=True)
    return None, None

def sync_ingame_whitelist_event(line: str):
    """Spiegelt Ingame Whitelist- und OP-Befehle direkt nach Supabase zurück."""
    if not (SERVER_ID and SUPABASE_URL and SUPABASE_KEY):
        return

    m_add = WL_ADD_REGEX.search(line)
    if m_add:
        player = m_add.group(1)
        acc_id, disc_id = get_account_id_by_username(player)
        if acc_id:
            payload = {
                "server_id": SERVER_ID,
                "account_id": acc_id,
                "discord_user_id": disc_id,
                "role": "player"
            }
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/map_server_whitelist"
            requests.post(url, headers=_supabase_headers(), json=payload, timeout=5)
            print(f"[SYNC] Ingame Whitelist Add: {player} synchronisiert.", flush=True)
        return

    m_rem = WL_REM_REGEX.search(line)
    if m_rem:
        player = m_rem.group(1)
        acc_id, _ = get_account_id_by_username(player)
        if acc_id:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/map_server_whitelist?server_id=eq.{SERVER_ID}&account_id=eq.{acc_id}"
            requests.delete(url, headers=_supabase_headers(), timeout=5)
            print(f"[SYNC] Ingame Whitelist Remove: {player} synchronisiert.", flush=True)
        return

    m_op_add = OP_ADD_REGEX.search(line)
    if m_op_add:
        player = m_op_add.group(1)
        acc_id, _ = get_account_id_by_username(player)
        if acc_id:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/map_server_whitelist?server_id=eq.{SERVER_ID}&account_id=eq.{acc_id}"
            requests.patch(url, headers=_supabase_headers(), json={"role": "server-admin"}, timeout=5)
            print(f"[SYNC] Ingame OP Granted: {player} -> server-admin synchronisiert.", flush=True)
        return

    m_op_rem = OP_REM_REGEX.search(line)
    if m_op_rem:
        player = m_op_rem.group(1)
        acc_id, _ = get_account_id_by_username(player)
        if acc_id:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/map_server_whitelist?server_id=eq.{SERVER_ID}&account_id=eq.{acc_id}"
            requests.patch(url, headers=_supabase_headers(), json={"role": "player"}, timeout=5)
            print(f"[SYNC] Ingame OP Revoked: {player} -> player synchronisiert.", flush=True)
        return


def get_log_mode() -> str:
    """Modi: 'off', 'game', 'all'."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return f.read().strip().lower()
        except Exception:
            pass
    return "off"


def send_discord(url: str, text: str):
    if not url:
        return
    try:
        requests.post(url, json={"content": text}, timeout=5)
    except Exception:
        pass


def wait_for_ready():
    for _ in range(120):
        time.sleep(2)
        try:
            cid = subprocess.check_output(["docker", "ps", "-q"], text=True).strip().split("\n")[0]
            if not cid:
                continue
            logs = subprocess.run(["docker", "logs", "--tail", "50", cid], capture_output=True, text=True)
            if "Done (" in (logs.stdout + logs.stderr):
                send_discord(STATUS_WEBHOOK, "✅ **Minecraft Server ist spielbereit!**\nDu kannst jetzt connecten.")
                break
        except Exception:
            pass


def stream_logs():
    last_check = time.time()
    while True:
        time.sleep(8)
        mode = get_log_mode()

        lines_to_send = []
        now = time.time()
        since_arg = str(int(last_check))
        last_check = now

        # 1. Game Container Logs
        try:
            cids = subprocess.check_output(["docker", "ps", "-q"], text=True).strip().split("\n")
            if cids and cids[0]:
                res = subprocess.run(
                    ["docker", "logs", "--since", since_arg, cids[0]],
                    capture_output=True,
                    text=True
                )
                raw_out = (res.stdout + res.stderr).strip()
                if raw_out:
                    for line in raw_out.splitlines():
                        sync_ingame_whitelist_event(line)
                        if mode != "off":
                            lines_to_send.append(f"[GAME] {line}")
        except Exception:
            pass

        if mode == "off":
            continue

        # 2. System- & Service-Logs (nur bei mode == 'all')
        if mode == "all":
            try:
                res = subprocess.run(
                    ["journalctl", "-u", "gameserver-*", "--since", f"@{since_arg}", "--no-pager", "-q"],
                    capture_output=True,
                    text=True
                )
                sys_out = res.stdout.strip()
                if sys_out:
                    lines_to_send.extend([f"[SYS] {l}" for l in sys_out.splitlines()])
            except Exception:
                pass

        if lines_to_send:
            recent = lines_to_send[-15:]
            chunk = "\n".join(recent)
            if len(chunk) > 1800:
                chunk = chunk[-1800:]
            send_discord(LOG_WEBHOOK, f"```asciidoc\n{chunk}\n```")


if __name__ == "__main__":
    import threading
    threading.Thread(target=wait_for_ready, daemon=True).start()
    stream_logs()