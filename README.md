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

Discord sendet Interaktionen an denselben API-Endpunkt wie die REST API. Lambda prüft die Ed25519-Signatur. Für Slash Commands antwortet Lambda sofort mit Discords deferred-Antwort (Typ `5`) und startet den eigentlichen Befehl als asynchrone Lambda-Invocation. Der Worker bearbeitet anschließend die ursprüngliche Discord-Antwort: zuerst „Befehl empfangen – ich versuche ihn auszuführen…“, danach das Ergebnis. Längere Texte werden wegen Discords Limit von 2.000 Zeichen pro Nachricht auf mehrere Nachrichten aufgeteilt. Das ist eine Bestätigung und eine abschließende Aktualisierung, kein laufender Fortschrittsstream.

Button-Interaktionen (z. B. die Bestätigung von `/server delete`) erhalten eine deferred message update-Antwort (Typ `6`); der Worker aktualisiert danach die Bestätigungsnachricht. Lambda benötigt deshalb die Umgebungsvariable `AWS_LAMBDA_FUNCTION_NAME` (von AWS bereitgestellt) und die Ausführungsrolle braucht `lambda:InvokeFunction` auf dieselbe Funktion.

Die registrierten Befehle werden in [`scripts/discord_commands.json`](./scripts/discord_commands.json) definiert:

| Befehl | Optionen | Beschreibung |
| --- | --- | --- |
| `/server start` | `[name] [duration] [log]` | Startet einen Server. Laufzeit z. B. `45m`, `8h`, `2d`; Standard `5m`. Log-Modus: `none`, `game`, `all`; Standard `none`. |
| `/server stop` | `[name]` | Stoppt den angegebenen laufenden Server oder ohne Namen den ersten aktiven Server. |
| `/server reload-files` | `server` (erforderlich) | Soll Agent-Dateien auf einem laufenden Server neu laden. Der Agent-Endpunkt `/reload-files` ist im aktuellen `control_api.py` wegen der vorherigen allgemeinen 404-Antwort nicht erreichbar; der Befehl funktioniert daher erst nach Behebung dieses Handler-Fehlers. |
| `/server status` | keine | Zeigt registrierte Server samt Status. |
| `/server create` | `name` (erforderlich), `[game]`, `[subdomain]` | Legt ein Server-Volume und einen Datenbankeintrag an; verknüpfte Accounts des Erstellers werden als Server-Admins eingetragen. |
| `/server delete` | `server` (erforderlich) | Zeigt eine Bestätigungsschaltfläche; danach versucht der Handler, das Volume zu löschen und markiert den Datenbankeintrag als gelöscht. Eine laufende VM wird dabei nicht beendet. |
| `/whitelist add` | `username`, `server` (erforderlich), `[role]` | Fügt einen registrierten Ingame-Account hinzu oder ändert dessen Rolle (`player`/`server-admin`). |
| `/whitelist remove` | `username`, `server` (erforderlich) | Entfernt einen Eintrag; nur Server-Ersteller bzw. Superadmins dürfen dies. |
| `/whitelist list` | `server` (erforderlich) | Zeigt Whitelist-Einträge des Servers. |
| `/status` | keine | Zeigt Serverstatus aus dem Serverkatalog bzw. bei Datenbankfehlern die Hetzner-Instanzen. |
| `/log` | `mode` (erforderlich), `[server]` | Setzt den Log-Modus (`all`, `game`, `off`); Standardserver ist `default`. |
| `/costs` | `[timeframe] [user]` | Kosten und Spielzeiten; Zeiträume: aktueller/letzter Monat, Jahr oder gesamte Laufzeit. |
| `/account` | `[user]` | Kontostand für `me`, einen Nutzer oder `all`. |
| `/cash add` | `user`, `amount` (erforderlich), `[currency] [note]` | Bucht eine Zahlung; erfordert zusätzlich die Admin-Rolle in `dim_users`. |
| `/addgameaccount` | `game`, `username` (beide erforderlich) | Verknüpft einen Ingame-Account mit dem Discord-Profil. Minecraft-Namen werden gegen Mojang geprüft. |
| `/help` | keine | Gibt die Befehlsübersicht und Nutzungshinweise aus. |

### Beispiele für `/server start`:

* `/server start` startet den Default-Server für 5 Minuten ohne Log-Streaming.
* `/server start name: skyblock duration: 45m log: game` startet den Server `skyblock` mit Game-Logs.
* `/server start duration: 12h log: all` startet den Default-Server mit Game- und System-Logs.

Aktuell enthält `aws_lambda/config.py` nur eine Spielkonfiguration für Minecraft. Obwohl einige Befehle ein `game`-Feld anbieten, ist daraus keine Unterstützung weiterer Gameserver-Images abzuleiten; das Bootstrap-Skript erstellt derzeit nur ein Minecraft-Compose-Setup.

---

## REST Control Plane API

Die konfigurierte öffentliche API-Basis ist `https://api.calvinkoch.ch`. Der Pfad wird in `aws_lambda/rest_api.py` geroutet. Die Lambda-Funktion prüft bei regulären REST-Anfragen den Token, verarbeitet `OPTIONS` für CORS und erwartet JSON für Requests mit Body.

### Authentifizierung

Jede reguläre REST-Anfrage verlangt einen gültigen Token. Unterstützt werden `x-auth-token`, `X-Auth-Token` oder `Authorization: Bearer $AUTH_SECRET`. Discord-Interaktionen verwenden stattdessen `x-signature-ed25519` und `x-signature-timestamp`, geprüft mit `DISCORD_PUBLIC_KEY`.

| Header-Feld | Beschreibung |
| --- | --- |
| `x-auth-token` / `X-Auth-Token` | Konfiguriertes `AUTH_SECRET`. |
| `Authorization` | Alternativ `Bearer $AUTH_SECRET`. |
| `Content-Type` | Für Requests mit JSON-Body: `application/json`. |

Die Routen werden nach Pfad bzw. bei der Root-URL nach `action` ausgewählt. Die Implementierung erzwingt keine HTTP-Methode; die Beispiele unten verwenden `POST`.

### Unterstützte Routen

| Pfad | Root-URL `action` | Verhalten |
| --- | --- | --- |
| `/server/start` oder `/start` | `start` | Erzeugt eine Hetzner-VM mit dem konfigurierten Volume und bootstrapped sie. |
| `/server/stop` oder `/stop` | `stop` | Stoppt den benannten Server oder ohne Auswahl den ersten aktiven Server. |
| `/server/create` | `server_create` | Erstellt ein 20-GB-Volume und Serverdatensatz. |
| `/server/delete` | `server_delete` | Versucht Volume und DNS-Einträge zu löschen und markiert den Datenbankeintrag als gelöscht. Eine eventuell noch laufende VM wird nicht gelöscht. |
| `/servers` | `list` | Gibt Server aus Supabase zurück; bei Fehlern weicht die Funktion auf Hetzner-Instanzen aus. |
| `/log` | `log` | Setzt den gespeicherten und, falls aktiv, den Live-Log-Modus. |
| `/costs` | — | Ruft `rpc/get_costs_summary` in Supabase auf. |
| `/account` | — | Ruft Nutzerkontostände ab. |
| `/cash` | — | Verbucht eine Zahlung und ggf. einen Wechselkurs. |
| `/exchange-rate` | `exchange_rate` | Liefert den Wechselkurs. |
| `/addgameaccount` | `addgameaccount` | Verknüpft einen Game-Account. |
| `/dns/sync` | `dns_sync` | Synchronisiert DNS-Einträge von GoDaddy nach Supabase. |
| `/dns/records` | `dns_records` | Liest DNS-Einträge aus Supabase. |
| `/whitelist/add` | `whitelist_add` | Fügt einen Account zur Server-Whitelist hinzu. |
| `/whitelist/remove` | `whitelist_remove` | Entfernt einen Whitelist-Account. |
| `/whitelist/list` | `whitelist_list` | Liest Whitelist-Einträge eines Servers. |
| `/server/reload-files` | `server_reload_files` | Löst einen Datei-Reload auf einer laufenden VM aus. |

Für Aufrufe an der Root-URL wird die Route als JSON-`action` angegeben, z. B. `{"action":"list"}`. Pfad-Routen wie `/costs`, `/account`, `/cash`, `/dns/sync`, `/dns/records` und die Whitelist-Pfade besitzen in der aktuellen Implementierung keine Root-`action`-Alternative, sofern diese nicht ausdrücklich in der Tabelle genannt ist.

### Beispiele

Server starten:

```json
{
  "game": "minecraft",
  "server_name": "default",
  "duration": "4h",
  "server_type": "cpx32",
  "log": "game"
}
```

`duration` akzeptiert `m`, `h` oder `d` (z. B. `45m`, `8h`, `2d`). Ungültige Werte werden aktuell auf `5m` zurückgesetzt. `log` kann `none`, `game` oder `all` sein.

Zum Beispiel mit `curl`:

```bash
curl -X POST "https://api.calvinkoch.ch/server/start" \
  -H "x-auth-token: $AUTH_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"game":"minecraft","server_name":"default","duration":"4h","log":"game"}'
```

Ein erfolgreicher Start antwortet mit `message`, `discord_summary`, `data` und `log_mode`; `data` enthält Hetzner-ID, Name, IP, Domain, Laufzeit, Typ und den von Hetzner gemeldeten Status. Die VM kann beim Response noch booten.

Root-Aufruf zum Auflisten:

```bash
curl -X POST "https://api.calvinkoch.ch/" \
  -H "x-auth-token: $AUTH_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"action":"list"}'
```

Die Antwort enthält normalerweise `servers` (Datensätze aus `dim_servers`); wenn Supabase nicht mit Status `200` antwortet, enthält sie stattdessen `data` mit Hetzner-Instanzen. Weitere Request-Felder ergeben sich aus der Route und den Handlern, insbesondere `server_name`, `discord_user_id`, `username`, `mode`, `target_uid` und `timeframe`.

### Benötigtes Supabase-Schema

Die Anwendung legt keine Tabellen oder RPC-Funktionen an. Die Supabase-Instanz muss die von den Handlern verwendeten Tabellen, Views und Funktionen bereitstellen, darunter `dim_users`, `dim_game_accounts`, `dim_servers`, `dim_dns_records`, `map_server_whitelist`, `fact_player_sessions`, `fact_server_runs`, `fact_user_payments`, `view_user_balances` und `rpc/get_costs_summary`.

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

## Hetzner-VM und persistentes Volume

`hetzner/bootstrap.sh` lädt die Agent-Skripte zur VM nach `/opt/gameserver-agent/`. Das Hetzner-Volume wird nach `/mnt/gamespeicher` gemountet und enthält persistente Daten:

```text
/mnt/gamespeicher/
├── secrets.env            # Von der Stage-1-Initialisierung geschriebene Secrets
├── server_run.json        # Lokaler Heartbeat/Cache für den Serverlauf
├── session_cache.json     # Offline-Cache für Spieler-Sessions
├── docker-compose.yml     # Beim ersten Start erzeugtes Minecraft-Compose-Setup
└── data/                  # Minecraft-Welt und Serverdaten
```

Die vier Systemd-Dienste laufen aus `/opt/gameserver-agent/`: `gameserver-logs.service`, `gameserver-tracker.service`, `gameserver-control.service` und `gameserver-guard.service`. Der Guard beendet den Server bei Ablauf der Laufzeit, nach mehr als 60 Minuten ohne Spieler (Idle-Prüfung beginnt nach 15 Minuten) oder nach `/stop`. Beim Shutdown synchronisiert er Spieler-Sessions, stoppt den Container, sendet finale Logs, unmountet das Volume und löscht die VM. Das Volume selbst wird dabei nicht gelöscht.

### Variablen in `secrets.env`

```env
AUTH_SECRET=dein-api-auth-secret
HETZNER_API_TOKEN=dein-hetzner-api-token
DISCORD_STATUS_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_LOG_WEBHOOK_URL=https://discord.com/api/webhooks/...
SUPABASE_URL=https://deine-id.supabase.co
SUPABASE_KEY=dein-supabase-key
```

Stage 1 schreibt diese Werte beim Erstellen der VM aus der Lambda-Konfiguration in die Datei und setzt die Dateirechte auf `600`. `GAME_NAME` und `VOLUME_DIR` werden durch das Bootstrap-Skript für die jeweiligen Systemd-Dienste gesetzt.

---

## Setup & Deployment

### 1. Lokale Entwicklungsumgebung

```bash
git clone <repo-url>
cd personal-server-hub
./setup_env.sh
source .venv/bin/activate
pytest
```

`setup_env.sh` erstellt `.venv`, installiert `requirements.txt` und richtet VS Code/Pylance ein. Es erzeugt keine `.env` und provisioniert keine Cloud-Ressourcen. Lege lokale Secrets bei Bedarf selbst in `.env` ab; `.env` ist in `.gitignore` enthalten. `scripts/register_discord_commands.py` benötigt `DISCORD_APPLICATION_ID` und `DISCORD_BOT_TOKEN` (aus der Umgebung oder `.env`).

Die bereitgestellte [`.env.example`](./.env.example) enthält Beispielwerte für Hetzner, Authentifizierung und eine Lambda Function URL. Für die Discord-Command-Registrierung müssen zusätzlich folgende Werte lokal gesetzt sein:

```env
DISCORD_APPLICATION_ID=deine_discord_application_id
DISCORD_BOT_TOKEN=dein_discord_bot_token
```

### 2. GitHub Actions Deployment

`.github/workflows/deploy.yml` baut und deployed bei Pushes auf `main` oder manuellem `workflow_dispatch`. Wenn die Discord-Registrierungsdatei oder das Registrierungsskript geändert wurde (oder der Workflow manuell gestartet wird), werden Slash Commands registriert, bevor Lambda-Paket und Code aktualisiert werden.

Benötigte GitHub Actions Secrets:

* `AWS_ACCESS_KEY_ID`
* `AWS_SECRET_ACCESS_KEY`
* `DISCORD_APPLICATION_ID`
* `DISCORD_BOT_TOKEN`

Die AWS-Zugangsdaten müssen das Deployment der Funktion `hetzner-server-controller` in `eu-central-1` erlauben. Der Workflow verwendet keinen `LAMBDA_FUNCTION_URL`-Secret.

### 3. AWS Lambda Konfiguration

Das Deployment kopiert `aws_lambda/` an die Paketwurzel; der konfigurierte Lambda-Handler muss daher `lambda_function.lambda_handler` lauten. Konfiguriere folgende Variablen unter **Configuration → Environment variables**:

| Variable | Zweck / Standard |
| --- | --- |
| `AUTH_SECRET` | Authentifizierung regulärer REST-Anfragen und der VM-Agent-Aufrufe. |
| `DISCORD_PUBLIC_KEY` | Erforderlicher öffentlicher Discord-Schlüssel für die Signaturprüfung. |
| `DISCORD_APPLICATION_ID` | Fallback Application ID für Interaktionen, wenn sie im Interaction-Payload fehlt. |
| `HETZNER_API_TOKEN` | Hetzner Cloud API. |
| `HETZNER_LOCATION` | Hetzner-Standort; Standard `nbg1`. |
| `AWS_REGION` | Region des Lambda-Clients; Standard `eu-central-1`. |
| `GODADDY_API_KEY`, `GODADDY_API_SECRET` | GoDaddy DNS API; erforderlich für DNS-Änderungen. |
| `GODADDY_DOMAIN` | DNS-Domain; Standard `calvinkoch.ch`. |
| `GODADDY_SUBDOMAIN` | Fallback-Subdomain für den Minecraft-Default-Server; Standard `mc`. |
| `SUPABASE_URL`, `SUPABASE_KEY` | Supabase REST API. |
| `DISCORD_STATUS_WEBHOOK_URL` | Statusmeldungen von den Gameserver-VMs. |
| `DISCORD_LOG_WEBHOOK_URL` | Logmeldungen der VMs; fällt auf `DISCORD_STATUS_WEBHOOK_URL` zurück. |
| `GITHUB_REPO_RAW` | Optionaler Raw-Content-Basis-URL für Stage 2; Standard verweist auf das `main`-Branch dieses Repositories. |

`AWS_LAMBDA_FUNCTION_NAME` wird von AWS bereitgestellt und muss dem Namen der deployten Funktion entsprechen; der Discord-Einstieg verwendet ihn für die asynchrone Selbstinvokation. Die Execution Role benötigt `lambda:InvokeFunction` auf diese Funktion. Setze das Function-Timeout auf mindestens 30 Sekunden für Worker-Aufrufe zu Hetzner, Supabase und VM-Agent. Der synchrone Discord-Einstieg antwortet vorher mit Deferred ACK.

Die aktuelle Konfiguration in `aws_lambda/config.py` enthält Minecraft mit Default-Volume `107045799`, Port `25565` und Typ `cpx32`; weitere Server werden anhand ihres Volume-/Typ-Eintrags in Supabase gestartet. `VOLUME_ID` aus der lokalen Beispielkonfiguration ist kein Lambda-Override für den Code, der den Default-Server auswählt.

### 4. Discord Interactions und Command-Registrierung

1. Im [Discord Developer Portal](https://discord.com/developers/applications) die Interactions Endpoint URL auf den öffentlichen HTTPS-Endpunkt der Lambda-API setzen (im beschriebenen Deployment `https://api.calvinkoch.ch`).
2. Den passenden Discord Public Key als `DISCORD_PUBLIC_KEY` in Lambda konfigurieren.
3. Global Slash Commands mit `DISCORD_APPLICATION_ID` und `DISCORD_BOT_TOKEN` registrieren:

```bash
source .venv/bin/activate
python scripts/register_discord_commands.py
```

Das Registrierungsskript liest die `PUT /applications/{application_id}/commands`-Antwort und aktualisiert daraus `aws_lambda/commands_cache.txt`. Die Command-Definitionen kommen aus `scripts/discord_commands.json`.
