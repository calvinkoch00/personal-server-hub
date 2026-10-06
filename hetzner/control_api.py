import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
CONFIG_FILE = "/tmp/discord_log_mode"


class ControlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        token = self.headers.get("x-auth-token")
        if AUTH_SECRET and token != AUTH_SECRET:
            self.send_response(401)
            self.end_headers()
            return

        if self.path == "/toggle-log":
            content_length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                body = json.loads(body_data.decode("utf-8"))
            except Exception:
                body = {}

            mode = body.get("mode", "game").lower()
            if mode not in ["all", "game", "off"]:
                mode = "game"

            with open(CONFIG_FILE, "w") as f:
                f.write(mode)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"mode": mode}).encode("utf-8"))

        elif self.path == "/stop":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "shutdown_received"}).encode("utf-8"))
            os.system("systemctl stop gameserver-guard.service &")
        else:
            self.send_response(404)
            self.end_headers()


def run():
    server = HTTPServer(("0.0.0.0", 8080), ControlHandler)
    server.serve_forever()


if __name__ == "__main__":
    run()