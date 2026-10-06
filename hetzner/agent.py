import argparse
import datetime
import http.server
import json
import os
import re
import socketserver
import subprocess
import threading
import time
import urllib.request
import urllib.error

parser = argparse.ArgumentParser()
parser.add_argument("--max-seconds", type=int, default=300)
parser.add_argument("--port", type=int, default=25565)
args = parser.parse_args()

VOLUME_DIR = os.environ.get("VOLUME_DIR", "/mnt/gamespeicher")
SECRETS_FILE = os.path.join(VOLUME_DIR, "secrets.env")


def load_env(filepath=SECRETS_FILE):
    config = {}
    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip().strip('"').strip("'")
    return config


secrets = load_env()
HTTP_PORT = 8080
AUTH_TOKEN = secrets.get("AUTH_SECRET", os.environ.get("AUTH_SECRET", ""))
HETZNER_TOKEN = secrets.get("HETZNER_API_TOKEN", "")
WEBHOOK_URL = secrets.get("DISCORD_STATUS_WEBHOOK_URL", "")
SUPABASE_URL = secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = secrets.get("SUPABASE_KEY", "")

# Tracking State
CONN_REGEX = re.compile(r"src=(?P<ip>[\d\.]+)\s+.*?sport=(?P<port>\d+)")
JOIN_LOG_REGEX = re.compile(r"(?i)(?P<player>[a-zA-Z0-9_\-]+).*?(?:logged in|joined the game)")
LEAVE_LOG_REGEX = re.compile(r"(?i)(?P<player>[a-zA-Z0-9_\-]+).*?(?:lost connection|left the game)")

active_sockets = {}  # key: "ip:port", value: {"session_id": str, "player": str, "joined_at": datetime, "fallback_end_at": datetime}
lock = threading.Lock()
idle_since = None
shutdown_initiated = False


# ================= Supabase Client =================
def supabase_request(endpoint: str, method: str = "POST", data: dict | list = None, headers: dict = None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{endpoint}"
    req_headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    if headers:
        req_headers.update(headers)

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except Exception as e:
        print(f"[SUPABASE] Request-Fehler: {e}")
        return None


def db_insert_session(player_name: str, joined_at: datetime.datetime) -> str | None:
    now_iso = joined_at.isoformat()
    payload = {
        "player_name": player_name,
        "joined_at": now_iso,
        "fallback_end_at": now_iso
    }
    res = supabase_request("player_sessions", method="POST", data=payload)
    if isinstance(res, list) and len(res) > 0:
        return res[0].get("id")
    return None


def db_heartbeat_flush(sessions: list):
    for sess in sessions:
        sess_id = sess.get("session_id")
        fallback_iso = sess.get("fallback_end_at").isoformat()
        if sess_id:
            supabase_request(
                f"player_sessions?id=eq.{sess_id}",
                method="PATCH",
                data={"fallback_end_at": fallback_iso}
            )


def db_close_session(session_id: str, end_time: datetime.datetime, reason: str):
    if not session_id:
        return
    end_iso = end_time.isoformat()
    supabase_request(
        f"player_sessions?id=eq.{session_id}",
        method="PATCH",
        data={
            "left_at": end_iso,
            "fallback_end_at": end_iso,
            "close_reason": reason
        }
    )


# ================= Discord & Shutdown =================
def notify_discord(msg: str):
    if not WEBHOOK_URL:
        return
    try:
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps({"content": msg}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except Exception as e:
        print(f"[DISCORD] Fehler: {e}")


def execute_graceful_shutdown():
    global shutdown_initiated
    with lock:
        if shutdown_initiated:
            return
        shutdown_initiated = True

    print("[AGENT] Graceful Shutdown eingeleitet...")
    notify_discord("💾 **Server stoppt:** Weltdaten werden gesichert...")

    now = datetime.datetime.now(datetime.timezone.utc)
    with lock:
        for socket_key, sess in list(active_sockets.items()):
            db_close_session(sess.get("session_id"), now, reason="graceful_shutdown")
        active_sockets.clear()

    # Container stoppen & Dateisystem synchronisieren
    subprocess.run(["docker", "compose", "stop", "-t", "60"], cwd=VOLUME_DIR)
    subprocess.run(["sync"])
    notify_discord("🛑 **Offline:** Welt gesichert. Hetzner-Instanz wird gelöscht.")

    try:
        with urllib.request.urlopen("http://169.254.169.254/hetzner/v1/metadata/instance-id", timeout=2) as r:
            server_id = r.read().decode().strip()
        del_req = urllib.request.Request(
            f"https://api.hetzner.cloud/v1/servers/{server_id}",
            headers={"Authorization": f"Bearer {HETZNER_TOKEN}"},
            method="DELETE"
        )
        urllib.request.urlopen(del_req, timeout=5)
    except Exception as e:
        print(f"[AGENT] VM Selbstlöschung fehlgeschlagen: {e}")


# ================= Conntrack & Log Streamer =================
def stream_conntrack(game_port: int):
    print(f"[CONNTRACK] Starte Netfilter-Stream für Port {game_port}...")
    cmd = ["conntrack", "-E", "-e", "NEW,DESTROY", "--dport", str(game_port)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        for line in iter(proc.stdout.readline, ''):
            now = datetime.datetime.now(datetime.timezone.utc)
            match = CONN_REGEX.search(line)
            if not match:
                continue

            socket_key = f"{match.group('ip')}:{match.group('port')}"

            with lock:
                if "[NEW]" in line:
                    if socket_key not in active_sockets:
                        sess_id = db_insert_session("unknown", now)
                        active_sockets[socket_key] = {
                            "session_id": sess_id,
                            "player": "unknown",
                            "joined_at": now,
                            "fallback_end_at": now
                        }
                        print(f"[CONNTRACK] Neuer Socket: {socket_key}")
                elif "[DESTROY]" in line:
                    if socket_key in active_sockets:
                        sess = active_sockets.pop(socket_key)
                        db_close_session(sess.get("session_id"), now, reason="socket_destroy")
                        print(f"[CONNTRACK] Socket getrennt: {socket_key}")
    except Exception as e:
        print(f"[CONNTRACK] Fehler im Stream: {e}")


def tail_minecraft_logs():
    log_path = os.path.join(VOLUME_DIR, "data", "logs", "latest.log")
    if not os.path.exists(log_path):
        log_path = os.path.join(VOLUME_DIR, "logs", "latest.log")

    print(f"[LOG_TAILER] Prüfe Log-Pfad: {log_path}")
    while not os.path.exists(log_path) and not shutdown_initiated:
        time.sleep(2)

    try:
        with open(log_path, "r", errors="ignore") as f:
            f.seek(0, 2)
            while not shutdown_initiated:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue

                join_m = JOIN_LOG_REGEX.search(line)
                if join_m:
                    pname = join_m.group("player")
                    with lock:
                        for s_key, data in active_sockets.items():
                            if data["player"] == "unknown":
                                data["player"] = pname
                                # Update Name in Supabase
                                if data.get("session_id"):
                                    supabase_request(
                                        f"player_sessions?id=eq.{data['session_id']}",
                                        method="PATCH",
                                        data={"player_name": pname}
                                    )
                                break
                    print(f"[LOG] Spieler beigetreten: {pname}")

                leave_m = LEAVE_LOG_REGEX.search(line)
                if leave_m:
                    pname = leave_m.group("player")
                    now = datetime.datetime.now(datetime.timezone.utc)
                    with lock:
                        for s_key in list(active_sockets.keys()):
                            if active_sockets[s_key]["player"] == pname:
                                sess = active_sockets.pop(s_key)
                                db_close_session(sess.get("session_id"), now, reason="game_log_leave")
                                break
                    print(f"[LOG] Spieler verlassen: {pname}")
    except Exception as e:
        print(f"[LOG_TAILER] Error: {e}")


# ================= Heartbeat & Inaktivitäts-Überwachung =================
def heartbeat_and_idle_monitor():
    global idle_since
    startup_grace_period = time.time() + 900  # 15 Minuten Schonfrist nach VM-Boot

    while not shutdown_initiated:
        time.sleep(60)
        now = datetime.datetime.now(datetime.timezone.utc)

        with lock:
            player_count = len(active_sockets)
            if player_count > 0:
                idle_since = None
                for s_key, sess in active_sockets.items():
                    sess["fallback_end_at"] = now
                db_heartbeat_flush(list(active_sockets.values()))
            else:
                if time.time() > startup_grace_period:
                    if idle_since is None:
                        idle_since = time.time()
                        print("[IDLE] Keine Spieler online. 10-Minuten-Timer gestartet.")
                    elif time.time() - idle_since >= 600:  # 10 Minuten
                        print("[IDLE] 10 Minuten inaktiv. Shutdown wird ausgelöst.")
                        threading.Thread(target=execute_graceful_shutdown).start()
                        break


def autokill_timer(seconds: int):
    time.sleep(seconds)
    print(f"[AGENT] Maximale Lebenszeit von {seconds}s abgelaufen. Fahre herunter...")
    execute_graceful_shutdown()


# ================= HTTP Server (Kompatibilität zu Hetzner /stop) =================
class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        token = self.headers.get("x-auth-token")
        if AUTH_TOKEN and token != AUTH_TOKEN:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "unauthorized"}')
            return

        if self.path == "/stop":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message": "shutdown initiated"}')
            threading.Thread(target=execute_graceful_shutdown).start()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    notify_discord("🟢 **Gameserver ist online & bereit!** (Session-Tracking aktiv)")

    # 1. Conntrack Stream starten
    threading.Thread(target=stream_conntrack, args=(args.port,), daemon=True).start()

    # 2. Log-Tailer starten
    threading.Thread(target=tail_minecraft_logs, daemon=True).start()

    # 3. Heartbeat & Inaktivitäts-Wächter starten
    threading.Thread(target=heartbeat_and_idle_monitor, daemon=True).start()

    # 4. Maximaler Kill-Timer (Sicherheitsnetz)
    if args.max_seconds > 0:
        threading.Thread(target=autokill_timer, args=(args.max_seconds,), daemon=True).start()

    # 5. HTTP API bereitstellen
    with socketserver.TCPServer(("", HTTP_PORT), Handler) as httpd:
        print(f"[AGENT] HTTP-Steuerung lauscht auf Port {HTTP_PORT}...")
        httpd.serve_forever()