#!/bin/bash
set -euo pipefail

echo "[BOOTSTRAP] Starte Stage-2 Bootloader..."

# 1. Host-Pakete sicherstellen
apt-get update -y
apt-get install -y conntrack jq python3-pip curl

# 2. Docker sicherstellen
if ! command -v docker &> /dev/null; then
    echo "[BOOTSTRAP] Docker wird installiert..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
fi

# 3. Hetzner Volume identifizieren & einhängen
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

if ! mountpoint -q "$MOUNT_DIR"; then
    mount -o discard,defaults "$VOLUME_DEV" "$MOUNT_DIR"
    echo "[BOOTSTRAP] Volume erfolgreich gemountet nach $MOUNT_DIR"
fi

# 4. Modulare Agenten von GitHub beziehen
AGENT_DIR="/opt/gameserver-agent"
mkdir -p "$AGENT_DIR"
echo "[BOOTSTRAP] Lade modulare Agenten aus GitHub..."

for script in lifecycle_guard.py session_tracker.py log_streamer.py control_api.py; do
    curl -fsSL -H "Cache-Control: no-cache" \
        "$GITHUB_REPO/hetzner/$script?ts=$(date +%s)" \
        -o "$AGENT_DIR/$script"
done

pip3 install --break-system-packages requests python-dotenv

# Log-Modus initial setzen (none, game, all)
LOG_MODE="${ENABLE_LOGGING:-none}"
if [ -n "${SERVER_ID:-}" ] && [ -n "${SUPABASE_URL:-}" ] && [ -n "${SUPABASE_KEY:-}" ]; then
    echo "[BOOTSTRAP] Lade persistenten log_status aus Supabase für Server $SERVER_ID..."
    FETCHED_MODE=$(curl -fsSL \
        -H "apikey: $SUPABASE_KEY" \
        -H "Authorization: Bearer $SUPABASE_KEY" \
        "$SUPABASE_URL/rest/v1/dim_servers?server_id=eq.$SERVER_ID&select=log_status" | jq -r '.[0].log_status // empty' || echo "")
    if [ -n "$FETCHED_MODE" ]; then
        BOOT_LOG_MODE="$FETCHED_MODE"
    fi
fi

if [ "$BOOT_LOG_MODE" = "none" ] || [ "$BOOT_LOG_MODE" = "off" ] || [ "$BOOT_LOG_MODE" = "false" ]; then
    echo "off" > /tmp/discord_log_mode
else
    echo "$BOOT_LOG_MODE" > /tmp/discord_log_mode
fi

# 5. Vier separate systemd Services erstellen

# Service 1: Log Streamer & Readiness
cat << EOF > /etc/systemd/system/gameserver-logs.service
[Unit]
Description=Gameserver Log Streamer & Readiness
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
EnvironmentFile=$MOUNT_DIR/secrets.env
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
EnvironmentFile=$MOUNT_DIR/secrets.env
Environment=VOLUME_DIR=$MOUNT_DIR
Environment=GAME_NAME=${GAME:-minecraft}
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
EnvironmentFile=$MOUNT_DIR/secrets.env
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
EnvironmentFile=$MOUNT_DIR/secrets.env
Environment=VOLUME_DIR=$MOUNT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $AGENT_DIR/lifecycle_guard.py --max-seconds ${MAX_SECONDS:-300}
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

# 6. Whitelist & OPs vorab aus Supabase ziehen (Boot Option A)
if [ -n "${SERVER_ID:-}" ] && [ -n "${SUPABASE_URL:-}" ] && [ -n "${SUPABASE_KEY:-}" ]; then
    echo "[BOOTSTRAP] Erstelle whitelist.json und ops.json aus Supabase..."
    WL_JSON=$(curl -fsSL \
        -H "apikey: $SUPABASE_KEY" \
        -H "Authorization: Bearer $SUPABASE_KEY" \
        "$SUPABASE_URL/rest/v1/map_server_whitelist?server_id=eq.$SERVER_ID&select=role,dim_game_accounts(ingame_username,mojang_uuid)" || echo "[]")

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

# 7. Spielcontainer via Docker Compose starten
if [ -f "$MOUNT_DIR/docker-compose.yml" ] || [ -f "$MOUNT_DIR/compose.yml" ]; then
    echo "[BOOTSTRAP] Starte Gameserver Container..."
    cd "$MOUNT_DIR"
    docker compose up -d
else
    echo "[BOOTSTRAP] Warnung: Keine docker-compose.yml in $MOUNT_DIR gefunden!"
fi

echo "[BOOTSTRAP] Stage-2 Boot abgeschlossen!"