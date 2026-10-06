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
    """Wartet auf das Minecraft Done-Signal."""
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


def get_container_id() -> str | None:
    try:
        res = subprocess.check_output(["docker", "ps", "-q"], text=True).strip().split("\n")
        return res[0] if res and res[0] else None
    except Exception:
        return None


def stream_logs():
    last_seen_timestamp = None

    # Initialen Timestamp setzen, damit keine alten Boot-Logs gespammt werden
    cid = get_container_id()
    if cid:
        init_run = subprocess.run(["docker", "logs", "-t", "--tail", "1", cid], capture_output=True, text=True)
        init_lines = (init_run.stdout + init_run.stderr).strip().splitlines()
        if init_lines:
            last_seen_timestamp = init_lines[-1].split(" ")[0]

    while True:
        time.sleep(10)

        # Wenn Logging deaktiviert ist, pausieren
        if not os.path.exists(LOG_FLAG_FILE):
            continue

        cid = get_container_id()
        if not cid:
            continue

        try:
            cmd = ["docker", "logs", "-t"]
            if last_seen_timestamp:
                cmd.extend(["--since", last_seen_timestamp])
            cmd.append(cid)

            result = subprocess.run(cmd, capture_output=True, text=True)
            raw_lines = (result.stdout + result.stderr).splitlines()

            new_lines_clean = []
            for line in raw_lines:
                if not line.strip():
                    continue

                parts = line.split(" ", 1)
                ts = parts[0]
                content = parts[1] if len(parts) > 1 else ""

                # Zeilen überspringen, die wir schon exakt verarbeitet haben
                if last_seen_timestamp and ts <= last_seen_timestamp:
                    continue

                new_lines_clean.append(content)
                last_seen_timestamp = ts

            # Nur senden, wenn auch tatsächlich neue Zeilen existieren
            if new_lines_clean:
                # Discord Message Limit einhalten (2000 Zeichen, max 15 Zeilen pro Batch)
                chunk = "\n".join(new_lines_clean[-15:])
                if len(chunk) > 1850:
                    chunk = chunk[-1850:]
                send_discord(LOG_WEBHOOK, f"📋 **Live-Logs:**\n```text\n{chunk}\n```")

        except Exception as e:
            print(f"[STREAMER] Fehler beim Log-Lesen: {e}")


if __name__ == "__main__":
    if "--enable-logging" in sys.argv:
        with open(LOG_FLAG_FILE, "w") as f:
            f.write("1")

    wait_for_ready()
    stream_logs()