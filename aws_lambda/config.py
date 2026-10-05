import os

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN", "")
VOLUME_ID = os.environ.get("VOLUME_ID", "107045799")
LOCATION = os.environ.get("LOCATION", "nbg1")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
MAX_LIFETIME_SECONDS = int(os.environ.get("MAX_LIFETIME_SECONDS", "20"))
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")

def get_cloud_init_script(max_seconds: int = 20) -> str:
    return f"""#cloud-config
write_files:
  - path: /root/autostart.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      mkdir -p /mnt/gamespeicher
      mount -o discard,defaults /dev/disk/by-id/scsi-0HC_Volume_{VOLUME_ID} /mnt/gamespeicher || true
      if [ -d "/mnt/gamespeicher" ]; then
        cd /mnt/gamespeicher && docker compose up -d || true
      fi
      sleep {max_seconds}
      SERVER_ID=$(curl -s http://169.254.169.254/hetzner/v1/metadata/instance-id)
      curl -s -X DELETE -H "Authorization: Bearer {HETZNER_API_TOKEN}" "https://api.hetzner.cloud/v1/servers/$SERVER_ID"

runcmd:
  - systemd-run --unit=server-autokill /root/autostart.sh
"""