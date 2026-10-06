import os
import re

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN", "")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
DISCORD_STATUS_WEBHOOK_URL = os.environ.get("DISCORD_STATUS_WEBHOOK_URL", "")
DISCORD_LOG_WEBHOOK_URL = os.environ.get("DISCORD_LOG_WEBHOOK_URL", "")
LOCATION = os.environ.get("HETZNER_LOCATION", "nbg1")

DEFAULT_GAME = "minecraft"

GAME_CONFIGS = {
    "minecraft": {
        "volume_id": 107045799,
        "port": 25565,
        "default_type": "cpx32"
    }
}


def get_game_config(game: str = "minecraft") -> dict:
    return GAME_CONFIGS.get(game.lower(), GAME_CONFIGS[DEFAULT_GAME])


def get_stage1_bootloader(
    volume_id: int,
    game_port: int = 25565,
    max_seconds: int = 300,
    enable_logging: str = "none"
) -> str:
    auth_secret = os.environ.get("AUTH_SECRET", "")
    hetzner_token = os.environ.get("HETZNER_API_TOKEN", "")
    discord_status = os.environ.get("DISCORD_STATUS_WEBHOOK_URL", "")
    discord_log = os.environ.get("DISCORD_LOG_WEBHOOK_URL", "")
    supabase_url = os.environ.get("SUPABASE_URL", "https://test.supabase.co")
    supabase_key = os.environ.get("SUPABASE_KEY", "test-sb-key")
    github_repo = os.environ.get(
        "GITHUB_REPO_RAW",
        "https://raw.githubusercontent.com/calvinkoch00/personal-server-hub/main"
    )

    return f"""#!/bin/bash
set -euo pipefail

echo "[STAGE-1] Starte Initialisierung..."

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

# 2. Secrets injizieren
cat << 'EOF_SECRETS' > "$MOUNT_DIR/secrets.env"
AUTH_SECRET="{auth_secret}"
HETZNER_API_TOKEN="{hetzner_token}"
DISCORD_STATUS_WEBHOOK_URL="{discord_status}"
DISCORD_LOG_WEBHOOK_URL="{discord_log}"
SUPABASE_URL="{supabase_url}"
SUPABASE_KEY="{supabase_key}"
EOF_SECRETS
chmod 600 "$MOUNT_DIR/secrets.env"

# 3. Umgebungsvariablen setzen
export VOLUME_ID="{volume_id}"
export GAME_PORT="{game_port}"
export MAX_SECONDS="{max_seconds}"
export ENABLE_LOGGING="{enable_logging}"
export GITHUB_REPO="{github_repo}"

# 4. bootstrap.sh laden
mkdir -p /opt/bootstrap
echo "[STAGE-1] Lade bootstrap.sh..."
curl -sSL -H "Cache-Control: no-cache" \\
  "$GITHUB_REPO/hetzner/bootstrap.sh?ts=$(date +%s)" \\
  -o /opt/bootstrap/bootstrap.sh

chmod +x /opt/bootstrap/bootstrap.sh
echo "[STAGE-1] Übergebe an Stage-2..."
exec /opt/bootstrap/bootstrap.sh
"""