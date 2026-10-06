import os
import sys
import time
import json
import threading
import subprocess
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

STATUS_WEBHOOK_URL = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
LOG_WEBHOOK_URL = os.environ.get("DISCORD_LOG_WEBHOOK_URL")
AUTH_SECRET = os.environ.get("AUTH_SECRET")
LOG_FLAG_FILE = "/tmp/discord_logging_enabled"

def send_status(content: str):
    if not STATUS_WEBHOOK_URL:
        return
    try:
        requests.post(STATUS_WEBHOOK_URL, json={"content": content}, timeout=5)
    except Exception as e:
        print(f"[AGENT] Status webhook error: {e}")

def send_log(content: str):
    target = LOG_WEBHOOK_URL or STATUS_WEBHOOK_URL
    if not target:
        return
    try:
        requests.post(target, json={"content": content}, timeout=5)
    except Exception as e:
        print(f"[AGENT] Log webhook error: {e}")

# 1. Readiness Check (Minecraft)
def wait_for_minecraft_ready():
    print("[AGENT] Starte Readiness Polling...")
    for _ in range(120):  # Bis zu 4 Minuten warten
        time.sleep(2)
        try:
            res = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True)
            container_id = res.stdout.strip().split("\n")[0]
            if not container_id:
                continue

            logs = subprocess.run(["docker", "logs", "--tail", "60", container_id], capture_output=True, text=True)
            output = logs.stdout + logs.stderr
            if "Done (" in output:
                print("[AGENT] Server bereit.")
                send_status("✅ **Minecraft Server ist vollständig hochgefahren und spielbereit!** 🚀\nDu kannst jetzt connecten.")
                break
        except Exception as e:
            print(f"[AGENT] Readiness Check Fehler: {e}")

# 2. Live Log Streaming Loop
def log_streamer_loop():
    last_log_time = time.time()
    while True:
        time.sleep(10)
        if not os.path.exists(LOG_FLAG_FILE):
            continue

        try:
            res = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True)
            container_id = res.stdout.strip().split("\n")[0]
            if not container_id:
                continue

            since_ts = int(last_log_time)
            last_log_time = time.time()
            logs = subprocess.run(
                ["docker", "logs", "--since", f"{since_ts}s", container_id],
                capture_output=True, text=True
            )
            raw = (logs.stdout + logs.stderr).strip()

            if raw:
                lines = raw.splitlines()[-15:]
                chunk = "\n".join(lines)
                if len(chunk) > 1900:
                    chunk = chunk[-1900:]
                send_log(f"📋 **Server Logs:**\n```\n{chunk}\n```")
        except Exception as e:
            print(f"[AGENT] Streaming Fehler: {e}")

# 3. Control HTTP Server auf Port 8080 für den /log Befehl
class ControlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        auth = self.headers.get("x-auth-token")
        if auth != AUTH_SECRET:
            self.send_response(401)
            self.end_headers()
            return

        if self.path == "/toggle-log":
            if os.path.exists(LOG_FLAG_FILE):
                os.remove(LOG_FLAG_FILE)
                enabled = False
                send_status("🛑 **Discord Live-Logging wurde deaktiviert.**")
            else:
                with open(LOG_FLAG_FILE, "w") as f:
                    f.write("1")
                enabled = True
                send_status("▶️ **Discord Live-Logging wurde aktiviert (alle 10s).**")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"logging": enabled}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_control_server():
    server = HTTPServer(("0.0.0.0", 8080), ControlHandler)
    server.serve_forever()

if __name__ == "__main__":
    if "--enable-logging" in sys.argv:
        with open(LOG_FLAG_FILE, "w") as f:
            f.write("1")

    threading.Thread(target=wait_for_minecraft_ready, daemon=True).start()
    threading.Thread(target=log_streamer_loop, daemon=True).start()
    threading.Thread(target=run_control_server, daemon=True).start()

    # Hauptprozess am Leben halten
    while True:
        time.sleep(3600)