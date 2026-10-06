import os
import sys
import time
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

STATUS_WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
LOG_WEBHOOK = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or STATUS_WEBHOOK
LOG_FLAG_FILE = "/tmp/discord_logging_enabled"

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
                send_discord(STATUS_WEBHOOK, "✅ **Minecraft Server ist spielbereit!** 🚀\nDu kannst jetzt connecten.")
                break
        except Exception:
            pass

def stream_logs():
    last_ts = int(time.time())
    while True:
        time.sleep(10)
        if not os.path.exists(LOG_FLAG_FILE):
            continue

        try:
            cid = subprocess.check_output(["docker", "ps", "-q"], text=True).strip().split("\n")[0]
            if not cid:
                continue
            now = int(time.time())
            logs = subprocess.run(["docker", "logs", "--since", f"{last_ts}s", cid], capture_output=True, text=True)
            last_ts = now

            content = (logs.stdout + logs.stderr).strip()
            if content:
                lines = content.splitlines()[-12:]
                chunk = "\n".join(lines)
                send_discord(LOG_WEBHOOK, f"📋 **Live-Logs:**\n```\n{chunk[:1800]}\n```")
        except Exception:
            pass

if __name__ == "__main__":
    if "--enable-logging" in sys.argv:
        with open(LOG_FLAG_FILE, "w") as f:
            f.write("1")

    # Erst Readiness warten, dann Streaming-Schleife
    wait_for_ready()
    stream_logs()