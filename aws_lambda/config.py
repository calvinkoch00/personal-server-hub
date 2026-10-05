import os
import re

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN")
LOCATION = os.environ.get("LOCATION", "nbg1")
AUTH_SECRET = os.environ.get("AUTH_SECRET")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY")
DISCORD_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

DEFAULT_GAME = "minecraft"
DEFAULT_LIFETIME_SECONDS = 300  # 5 Minuten Standard
MAX_LIFETIME_SECONDS = 7 * 24 * 3600  # 7 Tage Max

# Mapping: Spiel -> Volume-ID
VOLUME_MAPPING = {
    "minecraft": os.environ.get("VOLUME_ID_MINECRAFT", os.environ.get("VOLUME_ID", "107045799")),
}

def get_volume_for_game(game: str) -> tuple[int, str] | None:
    game_lower = game.lower().strip()
    vol_id = VOLUME_MAPPING.get(game_lower)
    if not vol_id:
        return None
    return int(vol_id), game_lower

def parse_start_args(raw_input: str | None) -> tuple[str, int, str]:
    if not raw_input or not raw_input.strip():
        return DEFAULT_GAME, DEFAULT_LIFETIME_SECONDS, "5 Minute(n)"

    parts = raw_input.strip().lower().split()
    duration_str = None
    game = DEFAULT_GAME

    for part in parts:
        if re.match(r"^\d+[mhd]?$", part):
            duration_str = part
        else:
            game = part

    if not duration_str:
        return game, DEFAULT_LIFETIME_SECONDS, "5 Minute(n)"

    match = re.match(r"^(\d+)([mhd])?$", duration_str)
    if not match:
        return game, DEFAULT_LIFETIME_SECONDS, "5 Minute(n)"

    val = int(match.group(1))
    unit = match.group(2) or "h"

    if unit == "m":
        seconds = val * 60
        readable = f"{val} Minute(n)"
    elif unit == "d":
        seconds = val * 86400
        readable = f"{val} Tag(e)"
    else:
        seconds = val * 3600
        readable = f"{val} Stunde(n)"

    if seconds > MAX_LIFETIME_SECONDS:
        return game, MAX_LIFETIME_SECONDS, "7 Tage (Maximum)"
    if seconds < 60:
        return game, 60, "1 Minute (Minimum)"

    return game, seconds, readable

def get_cloud_init_script(max_seconds: int = 300, volume_id: int = 107045799) -> str:
    return f"""#cloud-config
write_files:
  - path: /root/autostart.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      if ! command -v docker &> /dev/null; then
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
      fi
      mkdir -p /mnt/gamespeicher
      mount -o discard,defaults /dev/disk/by-id/scsi-0HC_Volume_{volume_id} /mnt/gamespeicher || true
      if [ -d /mnt/gamespeicher ]; then
        cd /mnt/gamespeicher && docker compose up -d || true
      fi
      sleep {max_seconds}
      SERVER_ID=$(curl -s http://169.254.169.254/hetzner/v1/metadata/instance-id)
      curl -s -X DELETE -H "Authorization: Bearer {HETZNER_API_TOKEN}" "https://api.hetzner.cloud/v1/servers/$SERVER_ID"
runcmd:
  - systemd-run --unit=server-autokill /root/autostart.sh
"""