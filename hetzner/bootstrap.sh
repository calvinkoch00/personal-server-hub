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

AUTH_HEADER=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_HEADER="-H \"Authorization: token ${GITHUB_TOKEN}\""
fi

echo "[BOOTSTRAP] Lade aktuellste agent.py aus GitHub..."
curl -sSL -H "Cache-Control: no-cache" ${AUTH_HEADER} \
  "${GITHUB_REPO}/hetzner/agent.py?ts=$(date +%s)" \
  -o "${AGENT_DIR}/agent.py"

# Python-Abhängigkeiten installieren (z. B. für Supabase REST-Calls)
pip3 install -q requests python-dotenv

# 5. systemd Service für den Agenten erstellen & starten
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
ExecStart=/usr/bin/python3 ${AGENT_DIR}/agent.py --max-seconds ${MAX_SECONDS:-300} --port ${GAME_PORT:-25565}
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