import os
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

AUTH_SECRET = os.environ.get("AUTH_SECRET")
STATUS_WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
LOG_WEBHOOK = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or STATUS_WEBHOOK
CONFIG_FILE = "/tmp/discord_log_mode"


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_POST(self):
        # 1. Umschalten für Discord Live-Logging (/log Befehl via Lambda)
        if self.path == "/toggle-log":
            if self.headers.get("x-auth-token") != AUTH_SECRET:
                self._send_json(401, {"error": "Unauthorized"})
                return

            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                payload = json.loads(body)
                mode = payload.get("mode", "game").lower()
            except Exception:
                mode = "game"

            if mode not in ["all", "game", "off"]:
                mode = "game"

            with open(CONFIG_FILE, "w") as f:
                f.write(mode)

            # Abwärtskompatibilität: Legacy Flag-Datei aktualisieren
            legacy_flag = "/tmp/discord_logging_enabled"
            if mode != "off":
                with open(legacy_flag, "w") as f:
                    f.write("1")
            elif os.path.exists(legacy_flag):
                os.remove(legacy_flag)

            self._send_json(200, {"mode": mode, "logging": mode != "off"})
            return

        # 2. Lokale Log-API für Gameserver-Plugins & interne Programme
        if self.path == "/emit-log":
            # Erlaubt Localhost (127.0.0.1) ohne Token, externe Calls benötigen AUTH_SECRET
            client_ip = self.client_address[0]
            if client_ip != "127.0.0.1" and self.headers.get("x-auth-token") != AUTH_SECRET:
                self._send_json(401, {"error": "Unauthorized"})
                return

            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8")
                payload = json.loads(body)
                message = payload.get("message", "").strip()

                if message and LOG_WEBHOOK:
                    requests.post(
                        LOG_WEBHOOK,
                        json={"content": f"📝 **Server-Event:**\n```\n{message[:1800]}\n```"},
                        timeout=3
                    )
                self._send_json(200, {"status": "dispatched"})
            except Exception as e:
                self._send_json(400, {"error": f"Invalid payload: {e}"})
            return

        # 3. Graceful Stop Befehl von Lambda / Discord
        if self.path == "/stop":
            if self.headers.get("x-auth-token") != AUTH_SECRET:
                self._send_json(401, {"error": "Unauthorized"})
                return

            # Signalisiere dem Guard-Prozess sofortigen Shutdown & Hetzner-Löschung
            with open("/tmp/force_shutdown", "w") as f:
                f.write("1")

            self._send_json(200, {"status": "stopping"})
            return

        self._send_json(404, {"error": "Not found"})


if __name__ == "__main__":
    print("[CONTROL-API] Starte HTTP-Server auf Port 8080...")
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()