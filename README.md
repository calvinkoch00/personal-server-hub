# On-Demand Gaming & Workload Server Hub

Serverlose Steuerungs-Infrastruktur zur On-Demand-Bereitstellung, Verwaltung und automatischen Terminierung von Gameservern in der Hetzner Cloud – gesteuert via Discord Slash-Commands oder REST-API über AWS CloudFront, AWS Lambda, GoDaddy DNS und einen lokalen Server-Agenten auf persistentem Speicher.

---

## Architektur-Übersicht

```
┌──────────────────────────────────────────────────────────┐
│                        Interfaces                        │
│   Discord Slash Commands             REST Clients / SPA  │
└─────────────┬─────────────────────────────────┬──────────┘
              │ (Ed25519 Signature)             │ (x-auth-token)
              ▼                                 ▼
┌──────────────────────────────────────────────────────────┐
│        api.calvinkoch.ch (AWS CloudFront CDN / SSL)      │
└─────────────────────────────┬────────────────────────────┘
                              │ HTTPS Origin Request
                              ▼
┌──────────────────────────────────────────────────────────┐
│                 AWS Lambda Control Plane                 │
│  • Discord Interaktions-Handler (Ping / Command ACK)     │
│  • GoDaddy DNS Manager (mc.calvinkoch.ch A-Record)       │
│  • Hetzner API Client (VM Lifecycle & Provisioning)      │
│  • Remote Stop-Trigger an Server-Agenten (:8080)         │
└───────────────────────┬──────────────┬───────────────────┘
   GoDaddy API (HTTPS)  │              │ Hetzner Cloud API (HTTPS)
   mc.calvinkoch.ch -> IP              ▼
┌──────────────────────────────────────────────────────────┐
│               Hetzner Cloud Infrastructure               │
│  ┌────────────────────────┐    ┌──────────────────────┐  │
│  │ Ephemere Compute VM    │    │ Persistentes Storage │  │
│  │ (z. B. CPX32)          │◄───┤ Volume: /dev/disk/.. │  │
│  │                        │    │ (/mnt/gamespeicher)  │  │
│  │ • cloud-init Mount     │    ├──────────────────────┤  │
│  │ • Docker Compose Up    │    │ • agent.py (:8080)   │  │
│  │ • Agent HTTP Listener  │    │ • secrets.env        │  │
│  │                        │    │ • docker-compose.yml │  │
│  │                        │    │ • Spielstände/Welten │  │
│  └───────────┬────────────┘    └──────────────────────┘  │
│              │                                           │
│              │ Webhook POST / Self-Delete API            │
│              ▼                                           │
│  ┌────────────────────────┐    ┌──────────────────────┐  │
│  │ Discord Channel Status │    │ Hetzner API Delete   │  │
│  │ (Boot / Save / Delete) │    │ (Restlose Löschung)  │  │
│  └────────────────────────┘    └──────────────────────┘  │
└──────────────────────────────────────────────────────────┘

```

* **Custom Domain & CDN:** `api.calvinkoch.ch` via AWS CloudFront mit automatischer SSL-Terminierung (`us-east-1` ACM) und Weiterleitung an die Lambda-Funktion in Frankfurt (`eu-central-1`).
* **Dynamic DNS Integration:** Bei jedem VM-Start aktualisiert Lambda automatisch den DNS-A-Record `mc.calvinkoch.ch` über die GoDaddy-API auf die neu zugewiesene IPv4-Adresse.
* **Persistentes Volume-First Storage:** Hetzner Cloud Volume (`107045799`, EXT4), gemountet unter `/mnt/gamespeicher`. Enthält nicht nur Spielstände und Konfigurationen, sondern auch den persistenten Microservice `agent.py` und die lokalen Umgebungsvariablen (`secrets.env`).
* **Ephemere Compute VMs:** Hetzner Cloud Instanzen (Standard: `CPX32`, 4 vCPUs, 8 GB RAM), die rein für die Laufzeit existieren. Die VM enthält keine persistenten Daten und wird nach Spielende rückstandslos gelöscht.
* **Graceful Shutdown & Data Integrity:**
* Der Stop-Befehl triggert HTTP `POST :8080/stop` auf der VM.
* Der Agent führt synchron `docker compose stop -t 60` und `sync` aus, wodurch PaperMC alle Chunks und Spielerdaten ohne Datenverlust speichert.
* Erst nach erfolgreichem Unmount und Datenabgleich löscht sich die VM eigenständig per `DELETE /servers/{id}` über die Hetzner API.
* **Live Statusmeldungen via Discord Webhook:** Der Server meldet Status-Updates (Bereit zum Verbinden, Sicherungsvorgang, Löschung) direkt aus dem laufenden Betrieb in den Discord-Kanal.

---

## Discord Slash Commands

Der Bot antwortet innerhalb von Millisekunden direkt auf Slash-Befehle im Chat:

| Befehl      | Parameter               | Beschreibung                                                                                                    |
| ----------- | ----------------------- | --------------------------------------------------------------------------------------------------------------- |
| `/start`  | `args` *(optional)* | Startet die Instanz, setzt den DNS-Record und startet Minecraft. Standard:`minecraft` mit 5 Minuten Laufzeit. |
| `/status` | *keine*               | Zeigt aktive Server samt IP-Adresse, Hostname, Typ und Status an.                                               |
| `/stop`   | *keine*               | Weist den Server-Agenten an, Minecraft sauber zu beenden, Chunks zu sichern und die VM restlos zu löschen.     |
| `/help`   | *keine*               | Liefert eine formatierte Übersicht aller registrierten Befehle und REST-Endpunkte.                             |

### Syntax-Beispiele für `/start`:

* `/start` $\rightarrow$ Startet Minecraft für standardmäßig **5 Minuten** (ideal zum Testen).
* `/start args: 2h` $\rightarrow$ Startet Minecraft für **2 Stunden**.
* `/start args: 30m` $\rightarrow$ Startet Minecraft für **30 Minuten**.
* `/start args: csgo 1d` $\rightarrow$ Startet den CS:GO-Container für **1 Tag**.
* `/start args: 14d` $\rightarrow$ Greift das Hard-Cap: wird automatisch auf das Maximum von **7 Tagen** gedeckelt.

---

## REST Control Plane API

Die Control Plane ist weltweit unter **`[https://api.calvinkoch.ch](https://api.calvinkoch.ch)`** erreichbar.

### Authentifizierung

Jeder reguläre API-Aufruf (außer Discord-Webhooks, die über Ed25519 signiert werden) erfordert den Auth-Header:

| Header-Feld                              | Typ        | Beschreibung                       |
| ---------------------------------------- | ---------- | ---------------------------------- |
| `x-auth-token` (oder `X-Auth-Token`) | `string` | Dein konfiguriertes`AUTH_SECRET` |
| `Content-Type`                         | `string` | `application/json`               |

---

### Endpunkte

#### 1. Server starten

Erstellt eine Hetzner-VM, mountet das Volume, aktualisiert den GoDaddy DNS-Record, startet Docker Compose und übergibt die geplante Lebenszeit an den Server-Agenten.

* **Methoden & Pfade:** `POST /start` oder `POST /` mit Body `{"action": "start"}`
* **URL:** `[https://api.calvinkoch.ch/start](https://api.calvinkoch.ch/start)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Request Body (optional):**

```json
{
  "game": "minecraft",
  "duration": "2h",
  "server_type": "cpx32"
}

```

**Response (`200 OK`):**

```json
{
  "message": "Server gestartet",
  "discord_summary": "🎮 MINECRAFT gestartet! IP: `2.28.203.66` (2 Stunde(n))",
  "data": {
    "server_id": 168873929,
    "name": "minecraft-ondemand",
    "status": "initializing",
    "ip": "2.28.203.66",
    "domain": "mc.calvinkoch.ch",
    "game": "minecraft",
    "server_type": "cpx32",
    "lifetime_seconds": 7200,
    "lifetime_readable": "2 Stunde(n)"
  }
}

```

---

#### 2. Server-Status abfragen

Ermittelt den aktuellen Betriebszustand und die IP-Adresse einer Instanz.

* **Methoden & Pfade:**
* `GET /status?server_id=<SERVER_ID>`
* `POST /status` mit Body `{"server_id": "<SERVER_ID>"}`
* `POST /` mit Body `{"action": "status", "server_id": "<SERVER_ID>"}`
* **URL:** `[https://api.calvinkoch.ch/status](https://api.calvinkoch.ch/status)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Response (`200 OK`):**

```json
{
  "data": {
    "server_id": 168873929,
    "status": "running",
    "ip": "2.28.203.66"
  }
}

```

---

#### 3. Alle aktiven Server auflisten

Liefert alle derzeit laufenden Instanzen des Hetzner-Projekts zurück.

* **Methoden & Pfade:** `GET /servers`, `POST /servers`, oder `POST /` mit Body `{"action": "list"}`
* **URL:** `[https://api.calvinkoch.ch/servers](https://api.calvinkoch.ch/servers)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Response (`200 OK`):**

```json
{
  "data": [
    {
      "server_id": 168873929,
      "name": "minecraft-ondemand",
      "status": "running",
      "ip": "2.28.203.66",
      "server_type": "cpx32",
      "created": "2026-10-05T18:00:00Z"
    }
  ]
}

```

---

#### 4. Server stoppen (Graceful Stop & Deletion)

Weist den Server-Agenten an, Minecraft kontrolliert zu beenden (`SIGTERM`, Chunk-Flush), unmountet das Volume und löscht die VM aus Hetzner.

* **Methoden & Pfade:** `POST /stop` oder `POST /` mit Body `{"action": "stop", "server_id": "<SERVER_ID>"}`
* **URL:** `[https://api.calvinkoch.ch/stop](https://api.calvinkoch.ch/stop)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Request Body (optional):**

```json
{
  "server_id": "168873929"
}

```

**Response (`200 OK`):**

```json
{
  "data": {
    "status": "graceful_triggered"
  }
}

```

---

#### 5. Hilfe & Befehlsübersicht abfragen

Liefert die formatierte Übersicht aller verfügbaren Befehle und Endpunkte.

* **Methoden & Pfade:** `GET /help`, `POST /help`, oder `POST /` mit Body `{"action": "help"}`
* **URL:** `[https://api.calvinkoch.ch/help](https://api.calvinkoch.ch/help)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

---

#### 6. CORS Preflight

* **Methode & Pfad:** `OPTIONS /*`
* **Response (`200 OK`):** Sendet CORS-Header (`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: *`) für Web-Frontends/SPAs zurück.

---

## Volume-Konfiguration (`/mnt/gamespeicher`)

Auf dem Hetzner-Volume verbleiben alle persistenten Dateien:

```text
/mnt/gamespeicher/
├── agent.py               # Lokaler HTTP-Trigger (Port 8080) für Lifecycle & Discord-Status
├── secrets.env            # Lokale Umgebungsvariablen (AUTH_SECRET, Tokens, Webhook)
├── docker-compose.yml     # Container-Definition (itzg/minecraft-server)
└── data/                  # PaperMC Welten, Chunks, Inventare, Server-Properties

```

### `/mnt/gamespeicher/secrets.env` Aufbau:

```env
AUTH_SECRET="dein-super-secret-auth-token"
HETZNER_API_TOKEN="dein-hetzner-cloud-api-token"
DISCORD_STATUS_WEBHOOK_URL="https://discord.com/api/webhooks/..."

```

---

## Status-Codes Übersicht

| Status               | Bedeutung                                                                        |
| -------------------- | -------------------------------------------------------------------------------- |
| `200 OK`           | Anfrage erfolgreich ausgeführt.                                                 |
| `400 Bad Request`  | Fehlende Pflichtfelder oder ungültiges Interaktionsformat.                      |
| `401 Unauthorized` | Fehlender/ungültiger`x-auth-token` bzw. fehlerhafte Discord Ed25519-Signatur. |
| `404 Not Found`    | Endpunkt oder Route nicht gefunden.                                              |
| `500 Server Error` | Interner Fehler oder Hetzner-API-Fehlschlag.                                     |

---

## Setup & Deployment

### 1. Lokales Setup

```bash
git clone <repo-url>
cd personal-server-hub
chmod +x setup_env.sh
./setup_env.sh

```

Erstelle eine `.env`-Datei für lokale Tests:

```env
API_BASE_URL=https://api.calvinkoch.ch
HETZNER_API_TOKEN=dein_hetzner_token
VOLUME_ID=107045799
LOCATION=nbg1
AUTH_SECRET=dein_api_secret
DISCORD_PUBLIC_KEY=dein_discord_public_key
DISCORD_APPLICATION_ID=deine_discord_app_id
DISCORD_BOT_TOKEN=dein_discord_bot_token
GODADDY_API_KEY=dein_godaddy_key
GODADDY_API_SECRET=dein_godaddy_secret
GODADDY_DOMAIN=calvinkoch.ch
GODADDY_SUBDOMAIN=mc

```

### 2. GitHub Secrets hinterlegen

Unter **Settings** → **Secrets and variables** → **Actions** eintragen:

* `AWS_ACCESS_KEY_ID`
* `AWS_SECRET_ACCESS_KEY`
* `LAMBDA_FUNCTION_URL` (Deine Function URL oder `[https://api.calvinkoch.ch](https://api.calvinkoch.ch)`)
* `DISCORD_APPLICATION_ID`
* `DISCORD_BOT_TOKEN`

### 3. AWS Lambda Umgebungsvariablen

In der AWS-Konsole unter der Lambda-Funktion (**Configuration** → **Environment variables**):

* `HETZNER_API_TOKEN`
* `VOLUME_ID`
* `AUTH_SECRET`
* `DISCORD_PUBLIC_KEY`
* `DISCORD_APPLICATION_ID`
* `DISCORD_BOT_TOKEN`
* `GODADDY_API_KEY`
* `GODADDY_API_SECRET`
* `GODADDY_DOMAIN`
* `GODADDY_SUBDOMAIN`

*Hinweis:* Das Lambda-Timeout sollte unter **General configuration** auf mindestens **30 Sekunden** gesetzt sein.

### 4. Discord Bot Konfiguration

1. Applikation im [Discord Developer Portal](https://www.google.com/search?q=https://discord.com/developers/applications) öffnen.
2. Unter **General Information** die **Interactions Endpoint URL** setzen auf:
   `[https://api.calvinkoch.ch](https://api.calvinkoch.ch)`
3. Discord validiert die URL sofort per PING-Request (`200 OK`).
4. Slash-Befehle werden bei jedem Deployment über GitHub Actions automatisch synchronisiert (oder manuell via `python3 scripts/register_discord_commands.py`).
