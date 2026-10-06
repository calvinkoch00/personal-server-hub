import os
import re

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN")
LOCATION = os.environ.get("LOCATION", "nbg1")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY")
DISCORD_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID")
DISCORD_STATUS_WEBHOOK_URL = os.environ.get("DISCORD_STATUS_WEBHOOK_URL", "")

# Supabase Secrets
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# GitHub Konfiguration
GITHUB_REPO_RAW = os.environ.get("GITHUB_REPO_RAW", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

DEFAULT_GAME = "minecraft"
DEFAULT_LIFETIME_SECONDS = 300
MAX_LIFETIME_SECONDS = 7 * 24 * 3600

GAME_CONFIG = {
    "minecraft": {
        "volume_id": int(os.environ.get("VOLUME_ID_MINECRAFT", os.environ.get("VOLUME_ID", "107045799"))),
        "port": 25565
    }
}


def get_game_config(game: str) -> tuple[int, int, str] | None:
    game_lower = game.lower().strip()
    cfg = GAME_CONFIG.get(game_lower)
    if not cfg:
        return None
    return cfg["volume_id"], cfg["port"], game_lower


def parse_start_args(raw_input: str | None) -> tuple[str, int, str]:
    """Parst Benutzereingaben wie 'minecraft 2h' oder '30m'."""
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


def get_stage1_bootloader(volume_id: int, game_port: int, max_seconds: int = 300) -> str:
    """Stage-1 Bootloader als reines Bash-Skript (verhindert Cloud-Init YAML-Parsing-Fehler)."""
    gh_token = os.environ.get("GITHUB_TOKEN", GITHUB_TOKEN)
    gh_repo = os.environ.get("GITHUB_REPO_RAW", GITHUB_REPO_RAW)
    auth_sec = os.environ.get("AUTH_SECRET", AUTH_SECRET)
    hetzner_tok = os.environ.get("HETZNER_API_TOKEN", HETZNER_API_TOKEN)
    discord_wh = os.environ.get("DISCORD_STATUS_WEBHOOK_URL", DISCORD_STATUS_WEBHOOK_URL)
    sb_url = os.environ.get("SUPABASE_URL", SUPABASE_URL)
    sb_key = os.environ.get("SUPABASE_KEY", SUPABASE_KEY)

    auth_header = f'-H "Authorization: token {gh_token}"' if gh_token else ""

    return f"""#!/bin/bash
set -euo pipefail

echo "[STAGE-1] Starte Initialisierung..."

# 1. Volume frühzeitig einhängen
MOUNT_DIR="/mnt/gamespeicher"
VOLUME_DEV="/dev/disk/by-id/scsi-0HC_Volume_{volume_id}"

mkdir -p "$MOUNT_DIR"

echo "[STAGE-1] Warte auf Block Volume $VOLUME_DEV..."
for i in {{1..30}}; do
  if [ -b "$VOLUME_DEV" ]; then
    echo "[STAGE-1] Volume Device gefunden!"
    break
  fi
  sleep 1
done

if ! mountpoint -q "$MOUNT_DIR"; then
  mount -o discard,defaults "$VOLUME_DEV" "$MOUNT_DIR"
  echo "[STAGE-1] Volume gemountet."
fi

# 2. Secrets zentral aus Lambda injizieren
cat << 'EOF_SECRETS' > "$MOUNT_DIR/secrets.env"
AUTH_SECRET="{auth_sec}"
HETZNER_API_TOKEN="{hetzner_tok}"
DISCORD_STATUS_WEBHOOK_URL="{discord_wh}"
SUPABASE_URL="{sb_url}"
SUPABASE_KEY="{sb_key}"
EOF_SECRETS
chmod 600 "$MOUNT_DIR/secrets.env"

# 3. Stage-2 Umgebungsvariablen setzen
export VOLUME_ID="{volume_id}"
export GAME_PORT="{game_port}"
export MAX_SECONDS="{max_seconds}"
export GITHUB_REPO="{gh_repo}"
export GITHUB_TOKEN="{gh_token}"

# 4. bootstrap.sh von GitHub laden und ausführen
mkdir -p /opt/bootstrap
echo "[STAGE-1] Lade bootstrap.sh..."
curl -sSL -H "Cache-Control: no-cache" {auth_header} \\
  "$GITHUB_REPO/hetzner/bootstrap.sh?ts=$(date +%s)" \\
  -o /opt/bootstrap/bootstrap.sh

chmod +x /opt/bootstrap/bootstrap.sh
echo "[STAGE-1] Übergebe an Stage-2..."
exec /opt/bootstrap/bootstrap.sh
"""