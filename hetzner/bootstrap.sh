#!/usr/bin/env bash
set -euo pipefail

# 1. System Environment laden (falls vorhanden)
if [ -f /etc/environment ]; then
    set -a
    . /etc/environment
    set +a
fi

echo "[BOOTSTRAP] Starte Stage-2 Bootloader..."

# Sichere Fallbacks für Umgebungsvariablen unter set -u
VOLUME_ID="${VOLUME_ID:-}"
GAME="${GAME:-minecraft}"
GAME_PORT="${GAME_PORT:-25565}"
MAX_SECONDS="${MAX_SECONDS:-${MAX_LIFETIME_SECONDS:-300}}"
BOOT_LOG_MODE="${ENABLE_LOGGING:-none}"
GITHUB_REPO="${GITHUB_REPO:-calvinkoch00/personal-server-hub}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
SERVER_ID="${SERVER_ID:-}"
SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_KEY="${SUPABASE_KEY:-}"

if [ -z "$VOLUME_ID" ]; then
    echo "[BOOTSTRAP] FEHLER: VOLUME_ID ist nicht gesetzt!"
    exit 1
fi

# 2. Host-Pakete sicherstellen
apt-get update -y -qq
apt-get install -y -qq conntrack jq python3-pip curl

# 3. Docker sicherstellen
if ! command -v docker &> /dev/null; then
    echo "[BOOTSTRAP] Docker wird installiert..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
fi

# 4. Hetzner Volume identifizieren, bei Bedarf formatieren & einhängen
MOUNT_DIR="/mnt/gamespeicher"
VOLUME_DEV="/dev/disk/by-id/scsi-0HC_Volume_${VOLUME_ID}"
mkdir -p "$MOUNT_DIR"

echo "[BOOTSTRAP] Warte auf Hetzner Block Volume $VOLUME_DEV..."
for i in {1..30}; do
    if [ -b "$VOLUME_DEV" ]; then
        echo "[BOOTSTRAP] Volume gefunden!"
        break
    fi
    sleep 1
done

if [ ! -b "$VOLUME_DEV" ]; then
    echo "[BOOTSTRAP] FEHLER: Block Device $VOLUME_DEV nach 30s nicht verfügbar!"
    exit 1
fi

# Dateisystem prüfen; falls unformatiert (frisches Volume), mit ext4 initialisieren
if ! blkid "$VOLUME_DEV" >/dev/null 2>&1; then
    echo "[BOOTSTRAP] Frisches Volume ohne Dateisystem erkannt. Formatiere mit ext4..."
    mkfs.ext4 -F "$VOLUME_DEV"
fi

if ! mountpoint -q "$MOUNT_DIR"; then
    mount -o discard,defaults "$VOLUME_DEV" "$MOUNT_DIR"
    echo "[BOOTSTRAP] Volume erfolgreich gemountet nach $MOUNT_DIR"
fi

# 5. Modulare Agenten von GitHub beziehen
AGENT_DIR="/opt/gameserver-agent"
mkdir -p "$AGENT_DIR"
echo "[BOOTSTRAP] Lade modulare Agenten aus GitHub..."

# GitHub Raw-URL sauber auflösen
if [[ "$GITHUB_REPO" =~ ^https?:// ]]; then
    RAW_BASE_URL="$GITHUB_REPO"
else
    RAW_BASE_URL="https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}"
fi

for script in lifecycle_guard.py session_tracker.py log_streamer.py control_api.py; do
    curl -fsSL -H "Cache-Control: no-cache" \
        "$RAW_BASE_URL/hetzner/$script?ts=$(date +%s)" \
        -o "$AGENT_DIR/$script"
done

pip3 install --break-system-packages requests python-dotenv

# Log-Modus ermitteln & persistent setzen (none, game, all)
if [ -n "$SERVER_ID" ] && [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_KEY" ]; then
    echo "[BOOTSTRAP] Lade persistenten log_status aus Supabase für Server $SERVER_ID..."
    FETCHED_MODE=$(curl -fsSL \
        -H "apikey: $SUPABASE_KEY" \
        -H "Authorization: Bearer $SUPABASE_KEY" \
        "$SUPABASE_URL/rest/v1/dim_servers?server_id=eq.$SERVER_ID&select=log_status" | jq -r '.[0].log_status // empty' 2>/dev/null || true)
    if [ -n "${FETCHED_MODE:-}" ]; then
        BOOT_LOG_MODE="$FETCHED_MODE"
    fi
fi

if [ "${BOOT_LOG_MODE:-none}" = "none" ] || [ "${BOOT_LOG_MODE:-none}" = "off" ] || [ "${BOOT_LOG_MODE:-none}" = "false" ]; then
    echo "off" > /tmp/discord_log_mode
else
    echo "$BOOT_LOG_MODE" > /tmp/discord_log_mode
fi

# Secrets-Datei für systemd absichern
touch "$MOUNT_DIR/secrets.env"

# 6. Vier separate systemd Services erstellen

# Service 1: Log Streamer & Readiness
cat << EOF > /etc/systemd/system/gameserver-logs.service
[Unit]
Description=Gameserver Log Streamer & Readiness
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
EnvironmentFile=-$MOUNT_DIR/secrets.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $AGENT_DIR/log_streamer.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Service 2: Session Tracker
cat << EOF > /etc/systemd/system/gameserver-tracker.service
[Unit]
Description=Gameserver Player Session Tracker
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
EnvironmentFile=-$MOUNT_DIR/secrets.env
Environment=VOLUME_DIR=$MOUNT_DIR
Environment=GAME_NAME=${GAME}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $AGENT_DIR/session_tracker.py
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

# Service 3: Control API
cat << EOF > /etc/systemd/system/gameserver-control.service
[Unit]
Description=Gameserver Control API (Port 8080)
After=network.target

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
EnvironmentFile=-$MOUNT_DIR/secrets.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $AGENT_DIR/control_api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Service 4: Lifecycle Guard
cat << EOF > /etc/systemd/system/gameserver-guard.service
[Unit]
Description=Gameserver Lifecycle Guard & Killswitch
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
EnvironmentFile=-$MOUNT_DIR/secrets.env
Environment=VOLUME_DIR=$MOUNT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $AGENT_DIR/lifecycle_guard.py --max-seconds ${MAX_SECONDS}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

systemctl enable --now gameserver-logs.service
systemctl enable --now gameserver-tracker.service
systemctl enable --now gameserver-control.service
systemctl enable --now gameserver-guard.service

echo "[BOOTSTRAP] Alle 4 Services gestartet!"

# 7. Whitelist & OPs vorab aus Supabase ziehen
if [ -n "$SERVER_ID" ] && [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_KEY" ]; then
    echo "[BOOTSTRAP] Erstelle whitelist.json und ops.json aus Supabase..."
    WL_JSON=$(curl -fsSL \
        -H "apikey: $SUPABASE_KEY" \
        -H "Authorization: Bearer $SUPABASE_KEY" \
        "$SUPABASE_URL/rest/v1/map_server_whitelist?server_id=eq.$SERVER_ID&select=role,dim_game_accounts(ingame_username,mojang_uuid)" 2>/dev/null || echo "[]")

    mkdir -p "$MOUNT_DIR/data"
    python3 -c "
import json
try:
    data = json.loads('''$WL_JSON''')
    whitelist = []
    ops = []
    for entry in data:
        acc = entry.get('dim_game_accounts') or {}
        uuid = acc.get('mojang_uuid')
        name = acc.get('ingame_username')
        if uuid and name:
            whitelist.append({'uuid': uuid, 'name': name})
            if entry.get('role') == 'server-admin':
                ops.append({'uuid': uuid, 'name': name, 'level': 4, 'bypassesPlayerLimit': False})
    with open('$MOUNT_DIR/data/whitelist.json', 'w') as f:
        json.dump(whitelist, f, indent=2)
    with open('$MOUNT_DIR/data/ops.json', 'w') as f:
        json.dump(ops, f, indent=2)
except Exception as e:
    print(f'[BOOTSTRAP WARNING] Whitelist Generierung Fehler: {e}')
" || echo "[BOOTSTRAP] Whitelist-Generierung übersprungen"
fi

# 8. Spielcontainer prüfen, bei Bedarf initialisieren und starten
cd "$MOUNT_DIR"

if [ ! -f "$MOUNT_DIR/docker-compose.yml" ] && [ ! -f "$MOUNT_DIR/compose.yml" ]; then
    echo "[BOOTSTRAP] Frisches Volume erkannt! Initialisiere Standard-Setup für: ${GAME}..."

    mkdir -p "$MOUNT_DIR/data"

    if [ "$GAME" = "minecraft" ]; then
        cat << 'EOF_COMPOSE' > "$MOUNT_DIR/docker-compose.yml"
services:
  mc:
    image: itzg/minecraft-server:latest
    container_name: mc-server
    restart: always
    ports:
      - "25565:25565"
    environment:
      EULA: "TRUE"
      TYPE: "PAPER"
      MEMORY: "6G"
      ENABLE_RCON: "true"
      RCON_PORT: "25575"
      RCON_PASSWORD: "minecraft_secret_rcon"
      ENABLE_WHITELIST: "TRUE"
      ENFORCE_WHITELIST: "TRUE"
      OVERRIDE_WHITELIST: "FALSE"
      ONLINE_MODE: "TRUE"
    volumes:
      - /mnt/gamespeicher/data:/data
EOF_COMPOSE
        echo "[BOOTSTRAP] docker-compose.yml für Minecraft erfolgreich erstellt."
    fi
fi

if [ -f "$MOUNT_DIR/docker-compose.yml" ] || [ -f "$MOUNT_DIR/compose.yml" ]; then
    echo "[BOOTSTRAP] Starte Gameserver Container via Docker Compose..."
    docker compose up -d
else
    echo "[BOOTSTRAP] Fehler: Keine docker-compose.yml vorhanden und kein Template gefunden!"
fi

echo "[BOOTSTRAP] Stage-2 Boot abgeschlossen!"