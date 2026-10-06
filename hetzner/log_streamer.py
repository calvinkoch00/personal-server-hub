import os
import sys
import time
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv("/mnt/gamespeicher/secrets.env")

STATUS_WEBHOOK = os.environ.get("DISCORD_STATUS_WEBHOOK_URL")
LOG_WEBHOOK = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or STATUS_WEBHOOK
CONFIG_FILE = "/tmp/discord_log_mode"


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
        if mode == "off":
            last_check = time.time()
            continue

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
                out = (res.stdout + res.stderr).strip()
                if out:
                    lines_to_send.extend([f"[GAME] {l}" for l in out.splitlines()])
        except Exception:
            pass

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
            # Auf maximal 15 Zeilen pro Batch und 1800 Zeichen begrenzen
            recent = lines_to_send[-15:]
            chunk = "\n".join(recent)
            if len(chunk) > 1800:
                chunk = chunk[-1800:]
            send_discord(LOG_WEBHOOK, f"```asciidoc\n{chunk}\n```")


if __name__ == "__main__":
    import threading
    threading.Thread(target=wait_for_ready, daemon=True).start()
    stream_logs()