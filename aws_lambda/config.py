import os
import re

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN", "")
VOLUME_ID = os.environ.get("VOLUME_ID", "107045799")
LOCATION = os.environ.get("LOCATION", "nbg1")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")

# 5 Minuten Standard, maximal 7 Tage (in Sekunden)
DEFAULT_LIFETIME_SECONDS = 300
MAX_LIFETIME_SECONDS = 7 * 24 * 3600  # 604800s

def parse_duration_to_seconds(duration_str: str | None) -> tuple[int, str]:
    """Wandelt Angaben wie '5m', '2h', '3d' in Sekunden um (max. 7 Tage)."""
    if not duration_str:
        return DEFAULT_LIFETIME_SECONDS, "5 Minuten"

    raw = str(duration_str).strip().lower()
    match = re.match(r"^(\d+)([mhd]?)$", raw)
    if not match:
        return DEFAULT_LIFETIME_SECONDS, "5 Minuten (Fallback)"

    val = int(match.group(1))
    unit = match.group(2) or "h"  # Standardeinheit falls nur eine Zahl übergeben wird: Stunden

    if unit == "m":
        seconds = val * 60
        readable = f"{val} Minute(n)"
    elif unit == "d":
        seconds = val * 86400
        readable = f"{val} Tag(e)"
    else:  # 'h'
        seconds = val * 3600
        readable = f"{val} Stunde(n)"

    # Hard-Cap: Maximal 7 Tage
    if seconds > MAX_LIFETIME_SECONDS:
        return MAX_LIFETIME_SECONDS, "7 Tage (Maximum)"
    
    # Minimum: 60 Sekunden
    if seconds < 60:
        return 60, "1 Minute (Minimum)"

    return seconds, readable

def get_cloud_init_script(max_seconds: int = 300, game: str = "minecraft") -> str:
    # Vorbereitung für spätere Spiele (z. B. csgo)
    docker_dir = f"/mnt/gamespeicher/{game}" if game != "minecraft" else "/mnt/gamespeicher"

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
      fi
      sleep {max_seconds}
      SERVER_ID=$(curl -s http://169.254.169.254/hetzner/v1/metadata/instance-id)
      curl -s -X DELETE -H "Authorization: Bearer {HETZNER_API_TOKEN}" "https://api.hetzner.cloud/v1/servers/$SERVER_ID"

runcmd:
  - systemd-run --unit=server-autokill /root/autostart.sh
"""