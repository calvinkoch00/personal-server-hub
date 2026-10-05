
# On-Demand Gaming & Workload Server Hub

Serverlose Steuerungs-Infrastruktur für Hetzner Cloud Gameserver via AWS Lambda.

## Architektur

- **Storage:** Persistentes Hetzner Cloud Volume (EXT4) mit Docker-Compose-Dateien
- **Compute:** Ephemere Hetzner Cloud VMs (CPX32), gestartet via AWS Lambda
- **Control Plane:** AWS Lambda Function URL mit x-auth-token Validierung

## Setup

1. Repository klonen: `git clone <repo-url>`
2. Lokale Variablen anlegen: `cp .env.example .env` (Werte in `.env` eintragen)
3. Lambda Secrets in GitHub hinterlegen (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`)
