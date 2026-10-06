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


def get_stage1_bootloader(volume_id: int, game_port: int, max_seconds: int = 300) -> str:
    """Stage-1 Bootloader: Schreibt Secrets, setzt Variablen und führt bootstrap.sh aus."""
    auth_header = f'-H "Authorization: token {GITHUB_TOKEN}"' if GITHUB_TOKEN else ""
    
    return f"""#cloud-config
runcmd:
  - |
    set -eu
    
    # 1. Volume frühzeitig einhängen, damit secrets.env geschrieben werden kann
    mkdir -p /mnt/gamespeicher
    VOLUME_DEV="/dev/disk/by-id/scsi-0HC_Volume_{volume_id}"
    
    for i in {{1..30}}; do
      if [ -b "${{VOLUME_DEV}}" ]; then
        break
      fi
      sleep 1
    done
    
    if ! mountpoint -q /mnt/gamespeicher; then
      mount -o discard,defaults "${{VOLUME_DEV}}" /mnt/gamespeicher
    fi

    # 2. Secrets zentral aus Lambda injizieren (chmod 600 schützt vor unberechtigtem Lesen)
    cat << 'EOF_SECRETS' > /mnt/gamespeicher/secrets.env
AUTH_SECRET="{AUTH_SECRET}"
HETZNER_API_TOKEN="{HETZNER_API_TOKEN}"
DISCORD_STATUS_WEBHOOK_URL="{DISCORD_STATUS_WEBHOOK_URL}"
SUPABASE_URL="{SUPABASE_URL}"
SUPABASE_KEY="{SUPABASE_KEY}"
EOF_SECRETS
    chmod 600 /mnt/gamespeicher/secrets.env

    # 3. Stage-2 Umgebungsvariablen setzen
    export VOLUME_ID="{volume_id}"
    export GAME_PORT="{game_port}"
    export MAX_SECONDS="{max_seconds}"
    export GITHUB_REPO="{GITHUB_REPO_RAW}"
    export GITHUB_TOKEN="{GITHUB_TOKEN}"

    # 4. bootstrap.sh laden und ausführen
    mkdir -p /opt/bootstrap
    curl -sSL -H "Cache-Control: no-cache" {auth_header} \\
      "${{GITHUB_REPO}}/hetzner/bootstrap.sh?ts=$(date +%s)" \\
      -o /opt/bootstrap/bootstrap.sh

    chmod +x /opt/bootstrap/bootstrap.sh
    exec /opt/bootstrap/bootstrap.sh
"""