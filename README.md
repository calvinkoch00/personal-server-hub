# On-Demand Gaming & Workload Server Hub

Serverlose Steuerungs-Infrastruktur zur On-Demand-Bereitstellung, Verwaltung und automatischen Terminierung von Gameservern in der Hetzner Cloud. Gesteuert via Discord Slash-Commands oder REST-API über AWS CloudFront, AWS Lambda, GoDaddy DNS, Supabase-Persistenz und modulare Systemd-Dienste auf persistentem Block-Storage.

---

## Architektur-Übersicht

```
┌────────────────────────────────────────────────────────────────────────┐
│                               Interfaces                               │
│        Discord Slash Commands                   REST Clients / SPA     │
└───────────────────┬──────────────────────────────────────┬─────────────┘
                    │ (Ed25519 Signature)                  │ (x-auth-token)
                    ▼                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│              api.calvinkoch.ch (AWS CloudFront CDN / SSL)              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTPS Origin Request
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        AWS Lambda Control Plane                        │
│  • Discord Interaktions-Handler (Type 5 Deferred ACK / Follow-ups)     │
│  • GoDaddy DNS Manager (mc.calvinkoch.ch A-Record Dynamic IP)          │
│  • Hetzner Cloud API Client (VM Lifecycle & Provisioning)              │
│  • Supabase Client (Account Linking & User Management)                 │
│  • Remote Stop & Log-Toggle Trigger an VM-Agent (:8080)                │
└─────────────────┬─────────────────┬───────────────────┬────────────────┘
  GoDaddy (HTTPS) │                 │ Hetzner (HTTPS)   │ Supabase REST (HTTPS)
  mc -> Host-IP   │                 ▼                   ▼
                  │  ┌───────────────────────────────────────────────────┐
                  │  │           Hetzner Cloud Infrastructure            │
                  │  │  ┌──────────────────────┐  ┌───────────────────┐  │
                  │  │  │ Ephemere Compute VM  │  │ Persistenter      │  │
                  │  │  │ (z. B. CPX32)        │◄─┤ Speicher          │  │
                  │  │  │                      │  │ (/mnt/gamespeicher│  │
                  │  │  │ • Multi-Stage Boot   │  ├───────────────────┤  │
                  │  │  │ • Docker Engine      │  │ • session_cache   │  │
                  │  │  │ • Systemd Daemons:   │  │ • secrets.env     │  │
                  │  │  │   - lifecycle_guard  │  │ • docker-compose  │  │
                  │  │  │   - session_tracker  │  │ • Spielstände/Welt│  │
                  │  │  │   - log_streamer     │  │ • Python Scripts  │  │
                  │  │  │   - control_api      │  │                   │  │
                  │  │  └──────────┬───────────┘  └───────────────────┘  │
                  │  └─────────────┼─────────────────────────────────────┘
                  │                │ Webhooks / Live Streams
                  ▼                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Discord Channel Notifications                        │
│  • Bereitschafts- & Statusmeldungen (Server online, IP-Zuweisung)      │
│  • Live Console Logs (Filterbar: game, all, none)                      │
│  • Shutdown- & Lifecycle-Warnungen                                     │
└────────────────────────────────────────────────────────────────────────┘

```

* **Custom Domain & CDN:** `api.calvinkoch.ch` via AWS CloudFront mit automatischer SSL-Terminierung (`us-east-1` ACM) und Weiterleitung an die Lambda-Funktion in Frankfurt (`eu-central-1`).
* **Dynamic DNS Integration:** Bei jedem VM-Start aktualisiert Lambda den DNS-A-Record `mc.calvinkoch.ch` über die GoDaddy-API auf die neu zugewiesene Host-IPv4.
* **Modulare Systemd-Agenten:** Statt eines monolithischen Skripts teilen vier spezialisierte Daemons die Aufgaben auf dem Server:
* `gameserver-guard.service` (`lifecycle_guard.py`): Überwacht die Lebensdauer, warnt vor dem Ablauf und initiiert den Graceful Shutdown.
* `gameserver-tracker.service` (`session_tracker.py`): Parst Docker-Logstreams live, cacht Spieler-Sessions im Volume und synchronisiert alle 10 Minuten gebündelt mit Supabase.
* `gameserver-streamer.service` (`log_streamer.py`): Pufferung und Übertragung von Konsolen- und Systemlogs per Discord Webhook (drei Modi: `none`, `game`, `all`).
* `gameserver-api.service` (`control_api.py`): Lokaler HTTP-Endpunkt auf Port 8080 für Remote-Steuerung (`/stop`, `/toggle-log`, `/emit-log`).
* **Offline-First Session Caching & Crash Recovery:**
* Jede Session erhält lokal eine eindeutige UUIDv4.
* Aktive Sessions werden minütlich mit einem Heartbeat (`fallback_end_at`) im Volume (`session_cache.json`) atomar gesichert.
* Alle 10 Minuten sowie beim Shutdown gleicht der Tracker die Daten per Upsert (`Prefer: resolution=merge-duplicates`) mit Supabase ab und löscht beendete Sessions aus dem lokalen Cache.
* Bei unvorhergesehenen Reboots oder Crashes liest der Tracker beim Start alte Cache-Reste aus, schließt diese als `crash_recovery` und lädt sie vollständig nach.
* **Graceful Shutdown Pipeline:**

1. `gameserver-tracker.service` schließt offene Sessions und synchronisiert den Cache restlos mit Supabase.
2. `docker compose stop -t 60` lässt PaperMC alle Chunks und Spielerdaten auf die Festplatte flushen.
3. Das Volume `/mnt/gamespeicher` wird sauber unmountet.
4. Die Hetzner-API erhält den `DELETE`-Aufruf zur vollständigen Zerstörung der ephemeren VM.

---

## Discord Slash Commands

Slash Commands werden zuerst mit `type: 5` (Deferred Channel Message) bestätigt. Sobald der asynchrone Lambda-Worker startet, aktualisiert er die ursprüngliche Discord-Antwort auf „Befehl empfangen – ich versuche ihn auszuführen…“ und ersetzt diese nach Abschluss durch das Ergebnis. Dadurch bekommt Discord rechtzeitig eine Bestätigung und die Nutzer sehen anschließend den tatsächlichen Command-Status.

| Befehl              | Option       | Typ    | Erforderlich | Beschreibung                                                                       |
| ------------------- | ------------ | ------ | ------------ | ---------------------------------------------------------------------------------- |
| `/start`          | `game`     | String | Nein         | Ziel-Spiel/Servertyp (Standard:`minecraft`).                                     |
|                     | `duration` | String | Nein         | Laufzeit frei eingeben (z. B.`45m`, `8h`, `2d` — Standard: `5m`).         |
|                     | `log`      | String | Nein         | Log-Stream-Modus (`none`, `game`, `all` — Standard: `none`).              |
| `/status`         | *keine*    | -      | -            | Zeigt alle aktiven Server samt IP-Adresse, Laufzeit und Hostname.                  |
| `/stop`           | *keine*    | -      | -            | Leitet den Graceful Shutdown ein (Sichern der Chunks, Session-Sync, VM-Löschung). |
| `/log`            | `mode`     | String | Ja           | Schaltet das Live-Logging im laufenden Betrieb um (`none`, `game`, `all`).   |
| `/addgameaccount` | `game`     | String | Ja           | Name des Spiels (z. B.`minecraft`).                                              |
|                     | `username` | String | Ja           | Ingame-Spielername zur Verknüpfung mit dem Discord-Account.                       |
| `/help`           | *keine*    | -      | -            | Gibt eine Übersicht aller Befehle und Bedienungshinweise aus.                     |

### Beispiele für `/start`:

* `/start` $\rightarrow$ Startet Minecraft für 5 Minuten ohne Log-Streaming.
* `/start duration: 45m log: game` $\rightarrow$ 45 Minuten Laufzeit, überträgt Spiel-Events (Joins, Leaves, Chat, Tode) live in Discord.
* `/start duration: 12h log: all` $\rightarrow$ 12 Stunden Laufzeit mit vollständigen Server- und System-Logs.
* `/start game: csgo duration: 2d` $\rightarrow$ Startet den CS:GO-Container für 2 Tage.

---

## REST Control Plane API

Die API ist weltweit über `[https://api.calvinkoch.ch](https://api.calvinkoch.ch)` erreichbar.

### Authentifizierung

Jeder reguläre API-Aufruf (außer Discord-Webhooks, die über Ed25519-Signaturen im Header validiert werden) verlangt den Auth-Header:

| Header-Feld                              | Typ        | Beschreibung                   |
| ---------------------------------------- | ---------- | ------------------------------ |
| `x-auth-token` (oder `X-Auth-Token`) | `string` | Konfiguriertes`AUTH_SECRET`. |
| `Content-Type`                         | `string` | `application/json`           |

---

### Endpunkte

#### 1. Server starten

Erstellt eine Hetzner-VM, mountet das Block-Volume, konfiguriert DNS, startet die Docker-Container und initialisiert die Systemd-Überwachungsdienste.

* **Methode & Pfad:** `POST /start` oder `POST /` mit Body `{"action": "start"}`
* **URL:** `[https://api.calvinkoch.ch/start](https://api.calvinkoch.ch/start)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Request Body (optional):**

```json
{
  "game": "minecraft",
  "duration": "4h",
  "server_type": "cpx32",
  "log": "game"
}

```

**Response (`200 OK`):**

```json
{
  "message": "Server gestartet",
  "discord_summary": "🎮 MINECRAFT gestartet! IP: `2.28.203.66` (4 Stunde(n))",
  "data": {
    "server_id": 168873929,
    "name": "minecraft-ondemand",
    "status": "initializing",
    "ip": "2.28.203.66",
    "domain": "mc.calvinkoch.ch",
    "game": "minecraft",
    "server_type": "cpx32",
    "lifetime_seconds": 14400,
    "lifetime_readable": "4 Stunde(n)",
    "logging": "game"
  }
}

```

---

#### 2. Server-Status & Instanzen abfragen

* **Pfade:** `GET /servers`, `POST /servers` oder `POST /` mit Body `{"action": "list"}`
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
      "created": "2026-10-06T15:00:00Z"
    }
  ]
}

```

---

#### 3. Live-Logs umschalten

Schaltet den Logging-Modus auf einer aktiven VM im laufenden Betrieb um.

* **Pfade:** `POST /log` oder `POST /` mit Body `{"action": "log", "mode": "all"}`
* **URL:** `[https://api.calvinkoch.ch/log](https://api.calvinkoch.ch/log)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Request Body:**

```json
{
  "mode": "all"
}

```

---

#### 4. Server stoppen (Graceful Shutdown)

Triggert den lokalen Agenten auf Port 8080, leert den Session-Cache nach Supabase, stoppt Docker, trennt das Volume und löscht die VM.

* **Pfade:** `POST /stop` oder `POST /` mit Body `{"action": "stop"}`
* **URL:** `[https://api.calvinkoch.ch/stop](https://api.calvinkoch.ch/stop)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Response (`200 OK`):**

```json
{
  "message": "Server minecraft-ondemand gelöscht",
  "hetzner_action": "stop_and_delete_invoked"
}

```

---

#### 5. Spieler-Account verknüpfen (Supabase Star-Schema)

Verknüpft einen Ingame-Namen mit einer Discord-ID in den Dimensionstabellen `dim_users` und `dim_game_accounts`.

* **Pfade:** `POST /addgameaccount` oder `POST /` mit Body `{"action": "addgameaccount"}`
* **URL:** `[https://api.calvinkoch.ch/addgameaccount](https://api.calvinkoch.ch/addgameaccount)`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

**Request Body:**

```json
{
  "discord_user_id": "432141301111324672",
  "discord_username": "gamesbond00",
  "game": "minecraft",
  "username": "gamesbond00"
}

```

---

## Supabase Star-Schema

Die PostgreSQL-Datenbank dient als relationale Single Source of Truth für Analysen und Spielerverwaltung:

```
┌─────────────────────────┐               ┌─────────────────────────┐
│        dim_users        │               │   dim_game_accounts     │
├─────────────────────────┤               ├─────────────────────────┤
│ discord_user_id (PK)    │◄───┐     ┌───►│ id (PK, UUID)           │
│ discord_username        │    │     │    │ discord_user_id (FK)    │
│ created_at              │    │     │    │ game                    │
└─────────────────────────┘    │     │    │ ingame_username         │
                               │     │    │ created_at              │
                               │     │    └─────────────────────────┘
                               │     │
                 ┌─────────────┴─────┴───────────┐
                 │      fact_player_sessions     │
                 ├───────────────────────────────┤
                 │ id (PK, UUID)                 │
                 │ discord_user_id (FK, Nullable)│
                 │ account_id (FK, Nullable)     │
                 │ game                          │
                 │ ingame_username               │
                 │ joined_at (TIMESTAMPTZ)       │
                 │ fallback_end_at (TIMESTAMPTZ) │
                 │ left_at (TIMESTAMPTZ, Nullable│
                 │ close_reason (Text, Nullable) │
                 │ duration_seconds (Int4)       │
                 │ created_at (TIMESTAMPTZ)      │
                 └───────────────────────────────┘

```

---

## Volume-Dateistruktur (`/mnt/gamespeicher`)

Alle persistenten Skripte, Caches und Spieldaten liegen auf dem Hetzner Cloud Volume:

```text
/mnt/gamespeicher/
├── lifecycle_guard.py     # Laufzeitwächter & Shutdown-Koordinator
├── session_tracker.py     # Docker Log-Parser & Supabase Batch-Sync Worker
├── log_streamer.py        # Discord Log-Streaming (Game/System/None)
├── control_api.py         # Lokale HTTP API (Port 8080)
├── session_cache.json     # Atomarer Offline-Cache für offene Sessions
├── secrets.env            # Lokale Umgebungsvariablen (Tokens, Keys, Webhooks)
├── docker-compose.yml     # Container-Setup (itzg/minecraft-server)
└── data/                  # PaperMC Chunks, Welten, Spielerdaten und Konfigurationen

```

### `/mnt/gamespeicher/secrets.env` Format:

```env
AUTH_SECRET="dein-api-auth-secret"
HETZNER_API_TOKEN="dein-hetzner-token"
DISCORD_STATUS_WEBHOOK_URL="https://discord.com/api/webhooks/..."
DISCORD_LOG_WEBHOOK_URL="https://discord.com/api/webhooks/..."
SUPABASE_URL="https://deine-id.supabase.co"
SUPABASE_KEY="dein-supabase-service-role-oder-anon-key"
GAME_NAME="minecraft"
VOLUME_DIR="/mnt/gamespeicher"

```

---

## Setup & Deployment

### 1. Lokales Setup

```bash
git clone <repo-url>
cd personal-server-hub
chmod +x setup_env.sh
./setup_env.sh

```

Erstelle eine `.env`-Datei für lokale Tests und CLI-Aufrufe:

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
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_KEY=dein_supabase_key

```

### 2. GitHub Actions Secrets

Trage unter **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions** folgende Variablen ein:

* `AWS_ACCESS_KEY_ID`
* `AWS_SECRET_ACCESS_KEY`
* `LAMBDA_FUNCTION_URL`
* `DISCORD_APPLICATION_ID`
* `DISCORD_BOT_TOKEN`

### 3. AWS Lambda Konfiguration

In der AWS-Konsole unter **Configuration** $\rightarrow$ **Environment variables**:

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
* `SUPABASE_URL`
* `SUPABASE_KEY`

*Wichtig:* Unter **General configuration** das Timeout der Lambda-Funktion auf **mindestens 30 Sekunden** erhöhen (Standard von 3 Sekunden führt zu Abbrüchen bei Hetzner- und Supabase-Aufrufen). Die Ausführungsrolle der Lambda-Funktion benötigt außerdem `lambda:InvokeFunction`-Berechtigung für genau diese Funktion, damit Discord-Interaktionen asynchron verarbeitet werden können.

### 4. Discord Bot Registrierung

1. Im [Discord Developer Portal](https://www.google.com/search?q=https://discord.com/developers/applications) deine Applikation öffnen.
2. Unter **General Information** die **Interactions Endpoint URL** eintragen:
   `[https://api.calvinkoch.ch](https://api.calvinkoch.ch)`
3. Slash Commands registrieren:

```bash
python scripts/register_discord_commands.py

```
