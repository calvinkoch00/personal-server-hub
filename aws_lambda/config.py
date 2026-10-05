import os
import re

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN", "")
VOLUME_ID = os.environ.get("VOLUME_ID", "107045799")
LOCATION = os.environ.get("LOCATION", "nbg1")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")

DEFAULT_GAME = "minecraft"
DEFAULT_LIFETIME_SECONDS = 300  # 5 Minuten
MAX_LIFETIME_SECONDS = 7 * 24 * 3600  # 7 Tage

def parse_start_args(raw_input: str | None) -> tuple[str, int, str]:
    """
    Erkennt Eingaben wie:
      - "" -> ('minecraft', 300, '5 Minuten')
      - "2h" -> ('minecraft', 7200, '2 Stunde(n)')
      - "valheim 3d" -> ('valheim', 259200, '3 Tag(e)')
    """
    if not raw_input or not raw_input.strip():
        return DEFAULT_GAME, DEFAULT_LIFETIME_SECONDS, "5 Minuten"

    parts = raw_input.strip().lower().split()
    game = DEFAULT_GAME
    duration_str = None

    for part in parts:
        if re.match(r"^\d+[mhd]?$", part):
            duration_str = part
        else:
            game = part

    if not duration_str:
        return game, DEFAULT_LIFETIME_SECONDS, "5 Minuten"

    match = re.match(r"^(\d+)([mhd]?)$", duration_str)
    val = int(match.group(1))
    unit = match.group(2) or "h"

    if unit == "m":
        seconds = val * 60
        readable = f"{val} Minute(n)"
    elif unit == "d":
        seconds = val * 86400
        readable = f"{val} Tag(e)"
    else:  # 'h'
        seconds = val * 3600
        readable = f"{val} Stunde(n)"

    if seconds > MAX_LIFETIME_SECONDS:
        return game, MAX_LIFETIME_SECONDS, "7 Tage (Maximum)"
    if seconds < 60:
        return game, 60, "1 Minute (Minimum)"

    return game, seconds, readable

def get_cloud_init_script(max_seconds: int = 300, game: str = "minecraft") -> str:
    # Verzeichnisstruktur auf dem persistenten Volume:
    # Standard: /mnt/gamespeicher (Minecraft)
    # Zukünftige Games: /mnt/gamespeicher/<game>
    docker_dir = f"/mnt/gamespeicher/{game}" if game != DEFAULT_GAME else "/mnt/gamespeicher"

    return f"""#cloud-config
write_files:
  - path: /root/autostart.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      mkdir -p /mnt/gamespeicher
      mount -o discard,defaults /dev/disk/by-id/scsi-0HC_Volume_{VOLUME_ID} /mnt/gamespeicher || true
      if [ -d "{docker_dir}" ]; then
        cd {docker_dir} && docker compose up -d || true
      elif [ -d "/mnt/gamespeicher" ]; then
        cd /mnt/gamespeicher && docker compose up -d || true
      fi
      sleep {max_seconds}
      SERVER_ID=$(curl -s http://169.254.169.254/hetzner/v1/metadata/instance-id)
      curl -s -X DELETE -H "Authorization: Bearer {HETZNER_API_TOKEN}" "https://api.hetzner.cloud/v1/servers/$SERVER_ID"

runcmd:
  - systemd-run --unit=server-autokill /root/autostart.sh
"""