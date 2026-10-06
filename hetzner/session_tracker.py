import os
import sys
import time
import datetime
import threading
import re
import signal
import requests
import subprocess
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
MOUNT_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")
GAME_NAME = os.environ.get("GAME_NAME", "minecraft").lower()

JOIN_REGEX = re.compile(
    r"UUID of player (?P<player>[a-zA-Z0-9_]{3,16}) is|"
    r": (?P<player2>[a-zA-Z0-9_]{3,16})\[.*\] logged in|"
    r": (?P<player3>[a-zA-Z0-9_]{3,16}) joined the game"
)
LEAVE_REGEX = re.compile(
    r": (?P<player>[a-zA-Z0-9_]{3,16}) lost connection|"
    r": (?P<player2>[a-zA-Z0-9_]{3,16}) left the game"
)

active_sessions: dict[str, dict] = {}
lock = threading.Lock()
running = True


def supabase_request(endpoint: str, method: str = "POST", data: dict | list = None) -> list | dict | None:
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    try:
        if method == "POST":
            r = requests.post(url, json=data, headers=headers, timeout=5)
        elif method == "PATCH":
            r = requests.patch(url, json=data, headers=headers, timeout=5)
        else:
            r = requests.get(url, headers=headers, timeout=5)

        if r.status_code in [200, 201]:
            return r.json() if r.text else None
        else:
            print(f"[TRACKER ERROR] Supabase API {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"[TRACKER ERROR] Supabase Exception: {e}", flush=True)
    return None


def lookup_discord_user(ingame_username: str) -> tuple[str | None, str | None]:
    res = supabase_request(
        f"dim_game_accounts?game=eq.{GAME_NAME}&ingame_username=ilike.{ingame_username}&select=id,discord_user_id",
        method="GET"
    )
    if isinstance(res, list) and len(res) > 0:
        return res[0].get("discord_user_id"), res[0].get("id")
    return None, None


def db_open_session(player_name: str) -> str | None:
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    discord_user_id, account_id = lookup_discord_user(player_name)

    payload = {
        "discord_user_id": discord_user_id,
        "account_id": account_id,
        "game": GAME_NAME,
        "ingame_username": player_name,
        "joined_at": now_iso,
        "fallback_end_at": now_iso
    }

    res = supabase_request("fact_player_sessions", method="POST", data=payload)
    if isinstance(res, list) and len(res) > 0:
        session_id = res[0].get("id")
        print(f"[TRACKER] + Session in fact_player_sessions erfasst: {player_name} (User: {discord_user_id})", flush=True)
        return session_id
    return None


def db_heartbeat_flush():
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with lock:
        items = list(active_sessions.items())

    for player, info in items:
        sid = info.get("session_id")
        if sid:
            supabase_request(
                f"fact_player_sessions?id=eq.{sid}",
                method="PATCH",
                data={"fallback_end_at": now_iso}
            )


def db_close_session(player_name: str, reason: str = "disconnect"):
    with lock:
        if player_name not in active_sessions:
            return
        info = active_sessions.pop(player_name)

    sid = info.get("session_id")
    if sid:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        supabase_request(
            f"fact_player_sessions?id=eq.{sid}",
            method="PATCH",
            data={
                "left_at": now_iso,
                "fallback_end_at": now_iso,
                "close_reason": reason
            }
        )
        print(f"[TRACKER] - Session beendet: {player_name} ({reason})", flush=True)


def tail_minecraft_logs():
    print("[TRACKER] Warte auf laufenden Docker-Container...", flush=True)
    cid = None
    while running and not cid:
        try:
            res = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True)
            cids = res.stdout.strip().split()
            if cids and cids[0]:
                cid = cids[0]
                break
        except Exception:
            pass
        time.sleep(1)

    print(f"[TRACKER] Tailing aktiv via Docker Container: {cid}", flush=True)

    try:
        # Liest stdout und stderr des Containers live ab dem Start
        proc = subprocess.Popen(
            ["docker", "logs", "-f", "--tail", "20", cid],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in iter(proc.stdout.readline, ''):
            if not running:
                break
            line = line.strip()
            if not line:
                continue

            # Join Event
            join_match = JOIN_REGEX.search(line)
            if join_match:
                pname = join_match.group("player") or join_match.group("player2") or join_match.group("player3")
                if pname and pname.lower() != "server":
                    with lock:
                        already_active = pname in active_sessions
                        if not already_active:
                            # Platzhalter sofort setzen, um Race-Conditions bei Folgezeilen abzufangen
                            active_sessions[pname] = {"session_id": None}
                    
                    if not already_active:
                        print(f"[TRACKER] Erkenne Join von: {pname}", flush=True)
                        sid = db_open_session(pname)
                        with lock:
                            if sid:
                                active_sessions[pname]["session_id"] = sid
                            else:
                                active_sessions.pop(pname, None)

            # Leave Event
            leave_match = LEAVE_REGEX.search(line)
            if leave_match:
                pname = leave_match.group("player") or leave_match.group("player2")
                if pname and pname.lower() != "server":
                    print(f"[TRACKER] Erkenne Leave von: {pname}", flush=True)
                    db_close_session(pname, reason="disconnect")

        proc.terminate()
    except Exception as e:
        print(f"[TRACKER ERROR] Docker Stream Fehler: {e}", flush=True)

def heartbeat_loop():
    while running:
        time.sleep(60)
        db_heartbeat_flush()


def handle_sigterm(signum, frame):
    global running
    print("[TRACKER] SIGTERM empfangen. Finalisiere offene Sessions...", flush=True)
    running = False
    with lock:
        players = list(active_sessions.keys())
    for p in players:
        db_close_session(p, reason="shutdown")
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    print(f"[TRACKER] Starte Fact-Session-Tracker für: {GAME_NAME}", flush=True)
    threading.Thread(target=tail_minecraft_logs, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    while running:
        time.sleep(1)


if __name__ == "__main__":
    main()