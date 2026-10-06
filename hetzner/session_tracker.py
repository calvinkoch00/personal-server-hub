import os
import sys
import time
import json
import uuid
import datetime
import threading
import subprocess
import re
import signal
import requests
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
MOUNT_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")
GAME_NAME = os.environ.get("GAME_NAME", "minecraft").lower()

CACHE_FILE = os.path.join(MOUNT_DIR, "session_cache.json")

JOIN_REGEX = re.compile(
    r"UUID of player (?P<player>[a-zA-Z0-9_]{3,16}) is|"
    r": (?P<player2>[a-zA-Z0-9_]{3,16})\[.*\] logged in|"
    r": (?P<player3>[a-zA-Z0-9_]{3,16}) joined the game"
)
LEAVE_REGEX = re.compile(
    r": (?P<player>[a-zA-Z0-9_]{3,16}) lost connection|"
    r": (?P<player2>[a-zA-Z0-9_]{3,16}) left the game"
)

lock = threading.Lock()
running = True

# active_players: ingame_username -> session_id
active_players: dict[str, str] = {}


# ==========================================
# Lokaler JSON Cache Helpers
# ==========================================

def load_cache() -> dict[str, dict]:
    """Lädt den lokalen Session-Cache vom Volume."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[CACHE ERROR] Konnte Cache nicht lesen: {e}", flush=True)
        return {}


def save_cache(cache_data: dict[str, dict]):
    """Schreibt den Cache atomar auf das gemountete Volume."""
    tmp_path = CACHE_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        os.replace(tmp_path, CACHE_FILE)
    except Exception as e:
        print(f"[CACHE ERROR] Fehler beim Schreiben des Caches: {e}", flush=True)


# ==========================================
# Supabase API Helpers (Upsert)
# ==========================================

def supabase_upsert_sessions(sessions: list[dict]) -> bool:
    """Sendet einen idempotenten Batch-Upsert an fact_player_sessions."""
    if not sessions or not (SUPABASE_URL and SUPABASE_KEY):
        return True

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/fact_player_sessions"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    try:
        r = requests.post(url, json=sessions, headers=headers, timeout=10)
        if r.status_code in [200, 201]:
            return True
        else:
            print(f"[SUPABASE SYNC ERROR] HTTP {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"[SUPABASE SYNC ERROR] Netzwerkfehler: {e}", flush=True)

    return False


def lookup_discord_user(ingame_username: str) -> tuple[str | None, str | None]:
    """Sucht Verknüpfung in dim_game_accounts."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None, None
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/dim_game_accounts?game=eq.{GAME_NAME}&ingame_username=ilike.{ingame_username}&select=id,discord_user_id"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            res = r.json()
            if isinstance(res, list) and len(res) > 0:
                return res[0].get("discord_user_id"), res[0].get("id")
    except Exception:
        pass
    return None, None


# ==========================================
# Session Management & Cache Logik
# ==========================================

def calculate_duration(joined_at_str: str, end_at_str: str) -> int:
    """Berechnet die Spieldauer in vollen Sekunden."""
    try:
        t_start = datetime.datetime.fromisoformat(joined_at_str)
        t_end = datetime.datetime.fromisoformat(end_at_str)
        return max(0, int((t_end - t_start).total_seconds()))
    except Exception:
        return 0


def flush_cache_to_supabase():
    """Gleicht Cache mit Supabase ab und löscht beendete Sessions."""
    with lock:
        cache = load_cache()
        if not cache:
            return

        all_sessions = list(cache.values())
        print(f"[SYNC] Starte Abgleich von {len(all_sessions)} Session(s) mit Supabase...", flush=True)

        success = supabase_upsert_sessions(all_sessions)
        if success:
            # Nur beendete Sessions aus dem lokalen Cache entfernen
            cleaned_cache = {}
            for sid, sdata in cache.items():
                if sdata.get("left_at") is None:
                    cleaned_cache[sid] = sdata  # noch aktiv -> behalten

            removed_count = len(cache) - len(cleaned_cache)
            save_cache(cleaned_cache)
            print(f"[SYNC] Erfolgreich! {removed_count} beendete Sessions aus lokalem Cache gelöscht. ({len(cleaned_cache)} aktive verbleiben)", flush=True)
        else:
            print("[SYNC] Abgleich fehlgeschlagen. Cache bleibt unverändert für nächsten Versuch erhalten.", flush=True)


def recover_orphan_sessions_on_boot():
    """Wird beim Start ausgeführt: Prüft alte Sessions von früheren Crashes."""
    with lock:
        cache = load_cache()
        if not cache:
            return

        print(f"[BOOT-RECOVERY] {len(cache)} Session(s) im lokalen Cache gefunden. Prüfe Integrität...", flush=True)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Offene Sessions von früher schließen (waren durch Crash nicht beendet worden)
        for sid, sdata in cache.items():
            if sdata.get("left_at") is None:
                end_iso = sdata.get("fallback_end_at") or now_iso
                sdata["left_at"] = end_iso
                sdata["close_reason"] = "crash_recovery"
                sdata["duration_seconds"] = calculate_duration(sdata.get("joined_at", end_iso), end_iso)

        save_cache(cache)

    flush_cache_to_supabase()


def on_player_join(player_name: str):
    with lock:
        if player_name in active_players:
            return

        session_id = str(uuid.uuid4())
        active_players[player_name] = session_id

        discord_user_id, account_id = lookup_discord_user(player_name)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        session_entry = {
            "id": session_id,
            "discord_user_id": discord_user_id,
            "account_id": account_id,
            "game": GAME_NAME,
            "ingame_username": player_name,
            "joined_at": now_iso,
            "fallback_end_at": now_iso,
            "left_at": None,
            "close_reason": None,
            "duration_seconds": None
        }

        cache = load_cache()
        cache[session_id] = session_entry
        save_cache(cache)

        print(f"[TRACKER] + Join: {player_name} (Session: {session_id[:8]}..., User: {discord_user_id}) -> Lokal gecacht", flush=True)


def on_player_leave(player_name: str, reason: str = "disconnect"):
    with lock:
        session_id = active_players.pop(player_name, None)
        if not session_id:
            return

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cache = load_cache()
        if session_id in cache:
            entry = cache[session_id]
            entry["left_at"] = now_iso
            entry["fallback_end_at"] = now_iso
            entry["close_reason"] = reason
            entry["duration_seconds"] = calculate_duration(entry.get("joined_at", now_iso), now_iso)
            save_cache(cache)
            print(f"[TRACKER] - Leave: {player_name} ({reason}) -> Im Cache als beendet markiert (Dauer: {entry['duration_seconds']}s)", flush=True)


def heartbeat_tick():
    """Aktualisiert jede Minute das fallback_end_at im lokalen Cache."""
    with lock:
        if not active_players:
            return

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cache = load_cache()
        updated = False

        for player_name, session_id in active_players.items():
            if session_id in cache:
                cache[session_id]["fallback_end_at"] = now_iso
                updated = True

        if updated:
            save_cache(cache)


# ==========================================
# Loops & Worker Threads
# ==========================================

def periodic_sync_and_heartbeat_loop():
    """Ticker: Alle 60s Heartbeat lokal speichern, alle 600s (10m) Sync zu Supabase."""
    counter = 0
    while running:
        time.sleep(60)
        counter += 1
        heartbeat_tick()

        # Alle 10 Minuten (10 * 60s)
        if counter % 10 == 0:
            flush_cache_to_supabase()


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

            join_match = JOIN_REGEX.search(line)
            if join_match:
                pname = join_match.group("player") or join_match.group("player2") or join_match.group("player3")
                if pname and pname.lower() != "server":
                    on_player_join(pname)

            leave_match = LEAVE_REGEX.search(line)
            if leave_match:
                pname = leave_match.group("player") or leave_match.group("player2")
                if pname and pname.lower() != "server":
                    on_player_leave(pname, reason="disconnect")

        proc.terminate()
    except Exception as e:
        print(f"[TRACKER ERROR] Docker Stream Fehler: {e}", flush=True)


def cleanup_and_flush_sync():
    """Wird synchron beim Beenden aufgerufen – blockiert bis alles bei Supabase ist."""
    print("[TRACKER] Shutdown-Signal empfangen. Schließe offene Sessions...", flush=True)
    with lock:
        players = list(active_players.keys())
    for p in players:
        on_player_leave(p, reason="shutdown")

    print("[TRACKER] Synchronisiere verbleibenden Cache mit Supabase...", flush=True)
    flush_cache_to_supabase()
    print("[TRACKER] Finaler Sync abgeschlossen. Beende Prozess sauber.", flush=True)


def handle_sigterm(signum, frame):
    global running
    running = False
    cleanup_and_flush_sync()
    os._exit(0)


def main():
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    print(f"[TRACKER] Starte robusten Session-Tracker (Offline-Cache & 10m-Sync) für: {GAME_NAME}", flush=True)

    # 1. Boot-Recovery: Evtl. gecachte Reste alter Sessions abgleichen
    recover_orphan_sessions_on_boot()

    # 2. Worker starten
    threading.Thread(target=tail_minecraft_logs, daemon=True).start()
    threading.Thread(target=periodic_sync_and_heartbeat_loop, daemon=True).start()

    while running:
        time.sleep(1)


if __name__ == "__main__":
    main()