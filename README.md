
# On-Demand Gaming & Workload Server Hub

Serverlose Steuerungs-Infrastruktur zur On-Demand-Bereitstellung, Verwaltung und automatischen Terminierung von Gameservern in der Hetzner Cloud – gesteuert via Discord Slash-Commands oder REST-API über AWS CloudFront & AWS Lambda.

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
│       api.calvinkoch.ch (AWS CloudFront CDN / SSL)       │
└─────────────────────────────┬────────────────────────────┘
                              │ HTTPS Origin Request
                              ▼
┌──────────────────────────────────────────────────────────┐
│                 AWS Lambda Control Plane                 │
│  • Discord Interaktions-Handler (Ping / Command ACK)     │
│  • Lokaler Command-Cache & dynamischer Help-Inspector    │
│  • Laufzeit-Parser & Hetzner API Client                  │
└─────────────────────────────┬────────────────────────────┘
                              │ Hetzner Cloud API (HTTPS)
                              ▼
┌──────────────────────────────────────────────────────────┐
│               Hetzner Cloud Infrastructure               │
│  ┌────────────────────────┐    ┌──────────────────────┐  │
│  │ Ephemere Compute VM    │    │ Persistentes Storage │  │
│  │ (z. B. CPX32)          │◄───┤ Volume: game-data    │  │
│  │                        │    │ (Docker-Dateien)     │  │
│  │ • cloud-init Mount     │    └──────────────────────┘  │
│  │ • Docker Compose Up    │                              │
│  │ • systemd-run AutoKill ├────── Self-Delete via API ───┘
│  └────────────────────────┘
```


- **Custom Domain & CDN:** `api.calvinkoch.ch` via AWS CloudFront mit automatischer SSL-Terminierung (`us-east-1` ACM) und Weiterleitung an die Lambda-Funktion in Frankfurt (`eu-central-1`).
- **Storage:** Persistentes Hetzner Cloud Volume (`game-data`, EXT4), das Spielstände, Konfigurationen und Docker-Compose-Dateien dauerhaft speichert.
- **Compute:** Ephemere Hetzner Cloud VMs (Standard: `CPX32`, 4 vCPUs, 8 GB RAM), die nur für die Spieldauer provisioniert und stundengenau abgerechnet werden.
- **Control Plane:** Serverlose AWS Lambda Function URL zur Verarbeitung von Discord-Interaktionen und REST-Requests.
- **Automatischer Shutdown:** Unabhängiger `systemd`-Service (`server-autokill`), der nach Ablauf des gewählten Zeitfensters (Standard: 5 Minuten, Maximal: 7 Tage) die eigene Server-Instanz über die Hetzner API terminiert. Das Volume wird dabei automatisch getrennt und bleibt erhalten.

---

## Discord Slash Commands

Der Bot reagiert direkt auf Slash-Befehle im Server:

| Befehl      | Parameter               | Beschreibung                                                                                                             |
| :---------- | :---------------------- | :----------------------------------------------------------------------------------------------------------------------- |
| `/start`  | `args` *(optional)* | Startet einen Server. Erkennt Spieltyp und Zeitdauer modular im Freitext. Standard:`minecraft` mit 5 Minuten Laufzeit. |
| `/status` | *keine*               | Listet alle aktiven Server samt IP-Adresse, Instanz-ID und Hardware-Status auf.                                          |
| `/stop`   | *keine*               | Terminiert die aktuell laufende Instanz sofort und unmounted das Volume sicher.                                          |
| `/help`   | *keine*               | Liefert eine formatierte Übersicht aller registrierten Befehle und REST-Endpunkte.                                      |

### Syntax-Beispiele für `/start`:

- `/start` $\rightarrow$ Startet Minecraft für standardmäßig **5 Minuten** (ideal zum Testen).
- `/start args: 2h` $\rightarrow$ Startet Minecraft für **2 Stunden**.
- `/start args: 30m` $\rightarrow$ Startet Minecraft für **30 Minuten**.
- `/start args: csgo 1d` $\rightarrow$ Startet den CS:GO-Container für **1 Tag**.
- `/start args: 14d` $\rightarrow$ Greift das Hard-Cap: wird automatisch auf das Maximum von **7 Tagen** gedeckelt.

---

## REST Control Plane API

Die Control Plane ist weltweit unter **`https://api.calvinkoch.ch`** erreichbar.

### Authentifizierung

Jeder reguläre API-Aufruf (außer Discord-Webhooks, die über Ed25519 signiert werden) erfordert den Auth-Header:

| Header-Feld                              | Typ        | Beschreibung                       |
| :--------------------------------------- | :--------- | :--------------------------------- |
| `x-auth-token` (oder `X-Auth-Token`) | `string` | Dein konfiguriertes`AUTH_SECRET` |
| `Content-Type`                         | `string` | `application/json`               |

---

### Endpunkte

#### 1. Server starten

Erstellt eine Hetzner-VM, mountet das Volume `game-data`, startet Docker Compose und plant den Selbstlöschungs-Timer ein.

- **Methoden & Pfade:** `POST /start` oder `POST /` mit Body `{"action": "start"}`
- **URL:** `https://api.calvinkoch.ch/start`
- **Headers:** `x-auth-token: <AUTH_SECRET>`

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
    "game": "minecraft",
    "server_type": "cpx32",
    "lifetime_seconds": 7200,
    "lifetime_readable": "2 Stunde(n)"
  }
}

```

---

#### 2. Server-Status abfragen

Ermittelt den aktuellen Betriebszustand und die IP-Adresse einer bestimmten Instanz.

* **Methoden & Pfade:**
* `GET /status?server_id=<SERVER_ID>`
* `POST /status` mit Body `{"server_id": "<SERVER_ID>"}`
* `POST /` mit Body `{"action": "status", "server_id": "<SERVER_ID>"}`
* **URL:** `https://api.calvinkoch.ch/status`
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
* **URL:** `https://api.calvinkoch.ch/servers`
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

#### 4. Server manuell stoppen & löschen

Terminiert den Server vorzeitig. Das Volume wird automatisch freigegeben und bleibt unversehrt.

* **Methoden & Pfade:** `POST /stop` oder `POST /` mit Body `{"action": "stop", "server_id": "<SERVER_ID>"}`
* **URL:** `https://api.calvinkoch.ch/stop`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Request Body:**

```json
{
  "server_id": 168873929
}

```

**Response (`200 OK`):**

```json
{
  "data": {
    "message": "Server wird gelöscht",
    "action": {
      "id": 98765432,
      "status": "running",
      "command": "delete_server"
    }
  }
}

```

---

#### 5. Hilfe & Befehlsübersicht abfragen

Liefert die formatierte Übersicht aller verfügbaren Befehle und Endpunkte.

* **Methoden & Pfade:** `GET /help`, `POST /help`, oder `POST /` mit Body `{"action": "help"}`
* **URL:** `https://api.calvinkoch.ch/help`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Response (`200 OK`):**

```json
{
  "message": "Befehlsübersicht",
  "help": "📖 **Verfügbare Server-Befehle:**\n• `/help` — Zeigt alle Befehle und Beispiele an\n• `/start [args]` — Startet Server (z. B. '/start', '/start 2h' oder '/start csgo 1d')\n• `/status` — Zeigt alle aktiven Server an\n• `/stop` — Stoppt den laufenden Gameserver\n\n💡 *Beispiele für `/start`:*\n• `/start` *(Minecraft, 5 Minuten)*\n• `/start 2h` *(Minecraft, 2 Stunden)*\n• `/start csgo 1d` *(CS:GO, 1 Tag, max. 7d)*",
  "endpoints": [
    {"path": "POST /start", "description": "Startet Server (Body: game, duration, server_type)"},
    {"path": "GET /status?server_id=<id>", "description": "Status einer spezifischen Instanz"},
    {"path": "GET /servers", "description": "Liste aller aktiven Instanzen"},
    {"path": "POST /stop", "description": "Löscht Server (Body: server_id)"},
    {"path": "GET /help", "description": "Zeigt diese Hilfeübersicht"}
  ]
}

```

---

#### 6. CORS Preflight

* **Methode & Pfad:** `OPTIONS /*`
* **Response (`200 OK`):** Sendet CORS-Header (`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: *`) für Web-Frontends/SPAs zurück.

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

Das beiliegende Setup-Skript richtet automatisch die Python-Umgebung (`.venv`) und VS Code ein:

```bash
git clone <repo-url>
cd personal-server-hub
chmod +x setup_env.sh
./setup_env.sh

```

Erstelle eine `.env`-Datei für lokale Tests:

```env
API_BASE_URL=[https://api.calvinkoch.ch](https://api.calvinkoch.ch)
HETZNER_API_TOKEN=dein_hetzner_token
VOLUME_ID=107045799
VOLUME_NAME=game-data
LOCATION=nbg1
AUTH_SECRET=dein_api_secret
DISCORD_PUBLIC_KEY=dein_discord_public_key
DISCORD_APPLICATION_ID=deine_discord_app_id
DISCORD_BOT_TOKEN=dein_discord_bot_token

```

### 2. GitHub Secrets hinterlegen

Unter **Settings** → **Secrets and variables** → **Actions** eintragen:

* `AWS_ACCESS_KEY_ID`
* `AWS_SECRET_ACCESS_KEY`
* `LAMBDA_FUNCTION_URL` (Deine Function URL oder `https://api.calvinkoch.ch`)
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

### 4. Discord Bot Konfiguration

1. Applikation im [Discord Developer Portal](https://www.google.com/search?q=https://discord.com/developers/applications) öffnen.
2. Unter **General Information** die **Interactions Endpoint URL** setzen auf:
   [https://api.calvinkoch.ch](https://api.calvinkoch.ch)
3. Discord speichert und validiert die URL sofort per PING-Request (`200 OK`).
4. Slash-Befehle werden bei jedem Deployment über GitHub Actions automatisch synchronisiert (oder manuell via `python3 scripts/register_discord_commands.py`).
