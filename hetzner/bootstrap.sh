#!/bin/bash
set -euo pipefail

echo "[BOOTSTRAP] === Starte Stage-2 Bootloader ==="

# 1. Erforderliche Host-Pakete sicherstellen
apt-get update -qq
apt-get install -y -qq conntrack jq python3-pip curl

# 2. Docker sicherstellen
if ! command -v docker &> /dev/null; then
  echo "[BOOTSTRAP] Docker wird installiert..."
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
fi

# 3. Hetzner Volume identifizieren & einhängen
MOUNT_DIR="/mnt/gamespeicher"
VOLUME_DEV="/dev/disk/by-id/scsi-0HC_Volume_${VOLUME_ID}"

mkdir -p "${MOUNT_DIR}"

echo "[BOOTSTRAP] Warte auf Hetzner Block Volume ${VOLUME_DEV}..."
for i in {1..30}; do
  if [ -b "${VOLUME_DEV}" ]; then
    echo "[BOOTSTRAP] Volume gefunden!"
    break
  fi
  sleep 1
done

if ! mountpoint -q "${MOUNT_DIR}"; then
  mount -o discard,defaults "${VOLUME_DEV}" "${MOUNT_DIR}"
  echo "[BOOTSTRAP] Volume erfolgreich gemountet nach ${MOUNT_DIR}."
fi

# 4. Agenten von GitHub beziehen
AGENT_DIR="/opt/gameserver-agent"
mkdir -p "${AGENT_DIR}"

echo "[BOOTSTRAP] Lade aktuellste agent.py aus GitHub..."
curl -fsSL -H "Cache-Control: no-cache" \
  "${GITHUB_REPO}/hetzner/agent.py?ts=$(date +%s)" \
  -o "${AGENT_DIR}/agent.py"

# Python-Abhängigkeiten installieren (mit Flag für Ubuntu 24.04 PEP 668)
pip3 install --break-system-packages -q requests python-dotenv

# 5. systemd Service für den Agenten erstellen & starten
ENABLE_LOG_ARG=""
if [ "${ENABLE_LOGGING:-false}" = "true" ]; then
  ENABLE_LOG_ARG="--enable-logging"
fi

cat << EOF > /etc/systemd/system/gameserver-agent.service
[Unit]
Description=On-Demand Gameserver Lifecycle & Billing Agent
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=${AGENT_DIR}
Environment="GAME_PORT=${GAME_PORT:-25565}"
Environment="MAX_SECONDS=${MAX_SECONDS:-300}"
Environment="VOLUME_DIR=${MOUNT_DIR}"
EnvironmentFile=${MOUNT_DIR}/secrets.env
ExecStart=/usr/bin/python3 ${AGENT_DIR}/agent.py --max-seconds ${MAX_SECONDS:-300} --port ${GAME_PORT:-25565} ${ENABLE_LOG_ARG}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now gameserver-agent.service
echo "[BOOTSTRAP] Agent-Service gestartet."

# 6. Spielcontainer via Docker Compose starten
if [ -f "${MOUNT_DIR}/docker-compose.yml" ] || [ -f "${MOUNT_DIR}/compose.yaml" ]; then
  echo "[BOOTSTRAP] Starte Gameserver Container..."
  cd "${MOUNT_DIR}"
  docker compose up -d
else
  echo "[BOOTSTRAP] Warnung: Keine docker-compose.yml in ${MOUNT_DIR} gefunden!"
fi

echo "[BOOTSTRAP] === Stage-2 Boot abgeschlossen ==="