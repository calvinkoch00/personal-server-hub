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

---

# Teil II – API-Refactoring: Arbeitsplan und Entscheidungsprotokoll

> **Status (2026-10-08):** Dieser Abschnitt ist das verbindliche Arbeitsdokument für das geplante Refactoring. Der bestehende Betrieb und die oben dokumentierten Befehle/Routen beschreiben den aktuellen Stand; die unten beschriebenen Zielarchitektur- und Migrationsschritte sind Plan, nicht bereits implementierter Code. Nach jedem Refactoring-Batch wird dieser Abschnitt aktualisiert: erledigte Schritte, geänderte Annahmen, offene Fragen und nötige Folgearbeiten.

## Ziel und Leitlinien

Das Projekt soll für externe Entwickler leichter zu verstehen und sicherer zu ändern sein. Die REST-API wird der fachliche Vertrag: Operationen, Request-/Response-Schemas, Validierung und Dokumentation werden zuerst definiert. Discord bleibt eine Schnittstelle dazu und enthält keine zweite Implementierung der Geschäftsregeln.

Leitlinien:

1. **API-Vertrag zuerst:** REST-Routen und typisierte Schemas definieren die unterstützten Operationen. Discord-Befehle werden aus diesen Definitionen abgeleitet und rufen dieselben Anwendungsoperationen auf.
2. **Keine interne HTTP-Schleife:** Discord ruft innerhalb derselben Lambda-Anwendung nicht die eigene öffentliche REST-URL auf. REST- und Discord-Adapter teilen Anwendungslogik direkt; so gibt es keinen unnötigen Netzwerk-Hop oder doppelte Authentifizierung.
3. **Schnittstellen bleiben getrennt:** Discord-Signaturprüfung, Deferred ACKs, Lambda-Worker und Webhook-Updates sind Discord-/AWS-Transportverhalten, nicht fachliche Serverlogik.
4. **Provider bleiben austauschbare Integrationen:** Hetzner, Supabase, GoDaddy, Mojang und der VM-Agent werden hinter klaren Integrationsgrenzen angesprochen.
5. **VM-Agent bleibt ein eigener Laufzeitbereich:** Die auf den Spielservern installierten Skripte sind kein Teil der Lambda-API und werden nur mit abgestimmten Änderungen an Bootstrap, Download-URLs, Dateipfaden, Imports und Systemd-Diensten verschoben.
6. **Schrittweise und rückwärtsverträglich migrieren:** Bestehende Clients und REST-Pfade sollen nicht durch einen Struktur-Refactor unbeabsichtigt brechen.
7. **Cloud-Integrationstests sind ausdrücklich opt-in:** Tests, die Ressourcen anlegen oder löschen, werden nicht als normale Unit-Tests oder automatisch in jedem PR ausgeführt.

## Zielarchitektur (Vorschlag)

Vorgeschlagene Bibliotheken: **FastAPI + Pydantic** für HTTP-Routen, Schemas und OpenAPI; **Mangum** als AWS-Lambda-Adapter. Vor der Migration wird anhand der tatsächlich konfigurierten Lambda-Eventform (Function URL/CloudFront-Origin) ein kleiner Adapter-Prototyp getestet. Falls Mangum den produktiven Eventpfad nicht zuverlässig abbildet, wird der Lambda-Adapter gezielt angepasst; Geschäftslogik bleibt unabhängig von diesem Entscheid.

Vorgeschlagener Aufbau:

```text
src/personal_server_hub/
├── lambda_handler.py             # AWS-Einstieg: HTTP-Adapter oder asynchroner Worker
├── settings.py                   # Konfiguration und Validierung von Umgebungsvariablen
├── api/
│   ├── app.py                    # FastAPI-Anwendung, Middleware und Fehlerabbildung
│   ├── dependencies.py           # Authentifizierung und gemeinsame Request-Abhängigkeiten
│   ├── schemas/                  # Gemeinsame, typisierte Request-/Response-Schemas
│   └── routes/
│       ├── servers.py
│       ├── whitelist.py
│       ├── accounts.py
│       ├── billing.py
│       └── dns.py
├── application/                  # Fachliche Use Cases, unabhängig von HTTP/Discord
│   ├── servers.py
│   ├── whitelist.py
│   ├── accounts.py
│   ├── billing.py
│   └── dns.py
├── domain/                       # Fachliche Typen, Regeln und synchronisierte Enum-Daten
│   └── supabase_enums.json       # Generierter, pro Release aktualisierter Enum-Snapshot
├── integrations/                 # Hetzner-, Supabase-, GoDaddy-, Mojang- und VM-Agent-Clients
└── adapters/
    └── discord/
        ├── interactions.py       # Signaturprüfung, ACK, Worker- und Button-Lebenszyklus
        ├── command_map.py        # Discord-Optionen → API-Operationen und Request-Schemas
        └── responses.py          # Discord-Formatierung, Fortschritt und 2.000-Zeichen-Aufteilung

vm_agent/                         # Optionaler neuer Repository-Ordner für die VM-Laufzeit
├── bootstrap.sh
├── control_api.py
├── lifecycle_guard.py
├── log_streamer.py
└── session_tracker.py

scripts/
├── generate_discord_commands.py  # API-Definitionen → Discord-Registrierungspayload
├── sync_supabase_enums.py        # Sichere Enum-Abfrage → JSON-Snapshot
└── e2e/                          # Bewusst gestartete Live-Cloud-Tests

tests/
├── unit/
│   ├── application/
│   ├── api/
│   ├── integrations/
│   └── discord/
└── integration/
```

Das ist ein Zielbild, kein Zwang, jeden Ordner sofort einzuführen. Die genaue Modulaufteilung wird während der Migration an den vorhandenen Use Cases ausgerichtet. Insbesondere wird `vm_agent/` erst verschoben, wenn alle Remote-Download- und Systemd-Pfade gleichzeitig angepasst und geprüft werden können.

## Discord-Befehle aus den API-Definitionen erzeugen

**Beschlossene Zielrichtung:** Die Discord-Registrierung soll nicht länger eine unabhängig gepflegte zweite Definition sein. Ein Generator soll die Discord-Payload aus derselben API-Operationsbeschreibung erzeugen, die REST-Schemas und OpenAPI speist. Die generierte Payload wird vor der Registrierung validiert; die Discord-`/help`-Übersicht bzw. ihr Cache wird ebenfalls aus dieser Quelle abgeleitet.

OpenAPI allein enthält nicht alle Discord-spezifischen Details. Deshalb erhalten geeignete API-Operationen bzw. Schemas explizite Metadaten für Discord, beispielsweise:

- Slash-Command- und Subcommand-Namen, Beschreibungen und Optionsreihenfolge;
- Übersetzung von Discord-Optionen auf Request-Felder und API-Operationen;
- Discord-Optionstypen, Pflichtfelder, Choices oder Autocomplete;
- Discord-Berechtigungs-/Sichtbarkeitshinweise, soweit sie zum API-Vertrag gehören;
- Hinweise zur Interaktionsart, etwa Bestätigungsdialog vor einer destruktiven Operation.

Diese Metadaten bleiben deklarativ; sie enthalten keine Geschäftslogik. Der Discord-Adapter validiert und normalisiert die Optionen und ruft anschließend die gleiche Anwendungsoperation wie die REST-Route auf. Discord-UI-Bestätigung (beispielsweise vor dem Löschen) bleibt im Adapter; die Löschoperation und ihre fachliche Autorisierung bleiben zentral.

Discord hat Limits und Semantik, die nicht automatisch aus REST-Schemas folgen (unter anderem höchstens 25 statische Choices je Option). Der Generator muss solche Grenzen erkennen und mit einem klaren Fehler abbrechen oder, falls fachlich passend, Autocomplete verwenden. Er darf Optionen nicht stillschweigend abschneiden.

**Übergang:** `scripts/discord_commands.json` bleibt vorerst das aktuelle Registrierungsartefakt. In der Umstellungsphase generiert der neue Generator eine Payload und vergleicht sie mit der bisher registrierten Definition. Erst wenn Tests die Gleichheit bzw. jede beabsichtigte Verhaltensänderung abdecken, wird die JSON-Datei als manuell gepflegte Quelle entfernt oder als generiertes Artefakt gekennzeichnet. Registrierung bleibt ein expliziter Deployment-Schritt; Änderungen an generierten Commands müssen vor dem Lambda-Code-Deploy erfolgreich registriert/validiert werden.

## Supabase-Enums als API- und Discord-Verträge

**Zielrichtung:** PostgreSQL-Enums aus Supabase sollen, wo fachlich relevant, in der API-Typisierung/Validierung wiederverwendet werden. Die gleichen Werte sollen bei geeigneten Discord-Optionen als Choices angeboten werden. Die Anwendung soll einen separat abgelegten, generierten lokalen Snapshot der verwendeten Supabase-Enums haben; dieser Snapshot wird bei jedem Deployment aktualisiert und zusammen mit dem Lambda-Paket ausgeliefert.

**Verifizierter Ist-Stand:** Im aktuellen Repository sind keine Supabase-Migrationen, SQL-Enum-Definitionen oder sonstigen expliziten Enum-Katalogdateien enthalten. Das bisherige Deployment bezieht Discord-Credentials, aber keine Supabase-Datenbank-Verbindung für eine Schema-Introspektion. Daher sind tatsächliche Enum-Namen, -Werte und eine sichere, verfügbare Quelle für einen Live-Snapshot noch zu ermitteln. Bis dahin gelten die in Python/JSON/README gefundenen Werte als bestehende Anwendungswerte, nicht als bewiesener vollständiger PostgreSQL-Enum-Katalog.

Geplanter sicherer Ablauf:

1. Vor dem Implementieren alle betroffenen Supabase-Enums samt Schema-/Tabellenbezug und tatsächlichen Werten inventarisieren. Herausfinden, ob die Supabase-Definitionen über versionierte Migrationen oder eine vorhandene, autorisierte PostgreSQL-Verbindung verwaltet werden.
2. Als bevorzugte Live-Quelle eine eng begrenzte, nur lesende Schemaabfrage einrichten, die ausschließlich benötigte Enum-Namen und -Werte aus dem PostgreSQL-Katalog ausliest. Falls dies über einen RPC geschieht, muss er ausschließlich Metadaten zurückgeben, minimale Rechte haben und darf keine beliebigen SQL-Abfragen ermöglichen.
3. `scripts/sync_supabase_enums.py` im Build ausführen und den Snapshot als `supabase_enums.json` im Release-/Lambda-Paket erzeugen. Zugangsdaten kommen nur aus einem dafür freigegebenen Secret/CI-Mechanismus, niemals aus dem Repository oder einer öffentlich erreichbaren API.
4. Der Build validiert Snapshot-Schema, erwartete Enums und Werte. Bei fehlgeschlagener Abfrage, leerem/unerwartetem Ergebnis oder inkompatibler Enum-Änderung schlägt der Build deutlich fehl; er verwendet nicht unbemerkt einen veralteten Snapshot.
5. API-Modelle verwenden die erzeugten Enum-Werte nur für Felder, deren Werte tatsächlich dem Supabase-Typ entsprechen. Discord-Choices werden aus denselben Werten gebaut, sofern Größe und UX geeignet sind; größere oder dynamische Mengen benötigen Autocomplete.
6. Ein Test prüft, dass API-Validierung, Discord-Choices und Snapshot konsistent sind. DB-seitige Restriktionen und Autorisierung bleiben weiterhin in Supabase bzw. den zentralen Anwendungsregeln bestehen; ein lokaler Enum-Snapshot ersetzt keine Datenbankvalidierung.

Wenn kein sicherer Live-Zugriff für CI verfügbar ist, wird vor Implementierung entschieden, ob versionierte Supabase-Migrationen die maßgebliche Quelle werden. Ein stilles Fallback auf eine eingecheckte alte Datei trotz fehlgeschlagener Live-Aktualisierung ist nicht vorgesehen. Ob der generierte Snapshot zusätzlich im Repository versioniert wird oder nur im Build-Artefakt entsteht, wird nach Klärung des Schema-Deployments entschieden; unabhängig davon ist das ausgelieferte Paket nachvollziehbar an den Enum-Stand des Releases gebunden.

## REST-Operationsvertrag und Discord-Zuordnung

Die API definiert typisierte Operationen und Antworten für mindestens die bereits vorhandenen Funktionsbereiche. Die endgültigen Methoden, Pfade und Schema-Namen werden beim Contract-Test-Batch festgelegt:

| Fachbereich | Bestehendes Verhalten / vorgesehener API-Bereich |
| --- | --- |
| Server | Auflisten, Erstellen, Starten, Stoppen, Löschen, Log-Modus ändern, Agent-Dateien neu laden |
| Whitelist | Einträge hinzufügen, entfernen und auflisten; Rollen zentral validieren |
| Accounts | Kontostand bzw. Nutzerübersicht lesen; Game-Account verknüpfen |
| Billing | Kostenübersicht, Zahlungen verbuchen und Wechselkurs ermitteln |
| DNS | DNS-Datensätze lesen und mit GoDaddy synchronisieren |

Jede Discord-Subcommand-Aktion wird auf genau eine benannte API-Operation abgebildet. Das bedeutet gleiche Request-Schemas, Validierungs- und Autorisierungsregeln sowie gleiche Anwendungsfunktion; es bedeutet nicht, dass Discord einen HTTP-Request an die öffentliche API senden muss. Reine Anzeige-/Hilfebefehle dürfen mehrere lesende Operationen aggregieren, wenn das im Vertrag explizit festgelegt und getestet wird.

Die bisher vorhandenen REST-Pfade sollen zunächst als Kompatibilitätsadapter erhalten bleiben und auf die neuen Operationen delegieren. Ein API-Pfadbruch oder eine `/api/v1`-Einführung wird nicht stillschweigend mit dem internen Struktur-Refactor gekoppelt; die externe Versionierungsentscheidung wird getroffen, bevor alte Pfade entfernt werden.

## Entscheidungsprotokoll

### Bereits im Code bzw. in der bestehenden Dokumentation verankert

Diese Punkte werden als bestehendes Verhalten behandelt und bei der Migration durch Tests abgesichert, bis der Nutzer eine bewusste Produktänderung beschließt:

- Discord-Interaktionen nutzen Ed25519-Signaturprüfung; reguläre REST-Aufrufe nutzen `AUTH_SECRET`. Discord-Slash-Commands erhalten einen Deferred ACK und werden über eine zweite Lambda-Invocation verarbeitet. Der Worker aktualisiert die ursprüngliche Antwort; lange Texte werden auf Discord-konforme Nachrichten aufgeteilt.
- Discord-Button-Bestätigungen werden deferred beantwortet und die ursprüngliche Bestätigungsnachricht danach aktualisiert.
- Serverstart-Defaults umfassen `minecraft`, den Server-Slug `minecraft-default`, fünf Minuten Laufzeit und Log-Modus `none`. Laufzeiten akzeptieren Minuten, Stunden und Tage (`m`, `h`, `d`); ungültige Werte fallen derzeit auf fünf Minuten zurück.
- Die registrierte Whitelist-Rolle bietet `player` und `server-admin`; die tatsächliche globale Admin-Prüfung für Cash akzeptiert `admin` und `superadmin`. Rollen und Statuswerte müssen gegen die echten Supabase-Typen geprüft werden, bevor sie in eine gemeinsame Enum überführt werden.
- Zahlungen werden bei fehlender Discord-Währungsauswahl standardmäßig als CHF erfasst und nach EUR gutgeschrieben. Das ist ein Zahlungs-/Datenbankverhalten und darf nicht allein aus einer Discord-Choice abgeleitet werden.
- Minecraft ist die einzige in der Anwendung konfigurierte und im Bootstrap unterstützte Spielkonfiguration; vorhandene `game`-Eingaben beweisen keine Unterstützung weiterer Spiele.
- Das Löschen eines Servers verlangt im Discord-Flow eine Bestätigung und löscht laut bestehender Dokumentation Volume/DNS bzw. markiert den Datenbankeintrag, beendet aber nicht automatisch eine eventuell laufende VM. Das destruktive Verhalten muss explizit dokumentiert und getestet werden.
- Server-Stop ohne Auswahl nimmt derzeit den ersten aktiven Server. Bei nicht lesbarem Supabase-Serverkatalog fällt die Serverliste derzeit teilweise auf Hetzner-Instanzen zurück.
- Die API-Implementierung erzwingt derzeit keine HTTP-Methode auf ihren REST-Pfaden. Die Migration soll die Methoden explizit machen; vorhandene Clients und tatsächlich genutzte Aufrufmethoden sind zuvor zu ermitteln.
- Der Deployment-Workflow kopiert derzeit `aws_lambda/` an die Paketwurzel und setzt dadurch den Handler als `lambda_function.lambda_handler`. Er registriert globale Discord-Kommandos über Discords `PUT`-Route; die bestehende Definition liegt in `scripts/discord_commands.json`.
- `hetzner/bootstrap.sh` lädt VM-Dateien einzeln nach festgelegten Pfaden; Systemd startet Skripte anhand konkreter Dateinamen. Umbenennung/Verschiebung ist daher ein Deployment-Änderungspaket, nicht nur ein lokales Refactoring.
- `scripts/run_user_tests.py` ist als Live-Cloud-/Ressourcen-Test zu behandeln und nicht unaufgefordert im normalen Testlauf auszuführen.

### Vom Nutzer für dieses Refactoring vorgegeben

- Erst API-Operationen und Definitionen als fachlichen Vertrag strukturieren; Discord-Befehle sollen darauf 1:1 abgebildet werden und nicht eine zweite Geschäftslogik enthalten.
- Eine aufgeräumte, nachvollziehbare Projektstruktur mit kleineren, nach Zuständigkeit gruppierten Modulen schaffen.
- Prüfen, ob Discord-Befehlsdefinitionen aus der API selbst generiert/abgeleitet und automatisiert registriert werden können.
- Vorhandene Supabase-Enums für API-Werte wiederverwenden; eine separate lokale Enum-Datei als Cache nutzen und bei jedem Deployment aktualisieren.
- Dieses README ist die zentrale Arbeits- und Entscheidungsdokumentation. Es wird nach jedem Umsetzungsbatch angepasst und bildet Änderungen am Plan nachvollziehbar ab.

### Vorgeschlagene technische Entscheidungen – noch bei Umsetzung zu verifizieren

- FastAPI + Pydantic + Mangum für REST/OpenAPI und Lambda, vorbehaltlich eines Prototyps mit dem produktiven Lambda-Eventformat.
- Gemeinsame `application/`-Use-Cases; REST und Discord sind Transportadapter und rufen diese direkt auf.
- Deklarative API-Metadaten ergänzen OpenAPI um Discord-Command-/Optionsdefinitionen; ein Generator erzeugt Registrierung und Hilfeansicht.
- Supabase-Enums beim Deployment sicher aus der maßgeblichen DB-Schemaquelle lesen und in einen validierten JSON-Snapshot für das Lambda-Paket schreiben.
- Bestehende REST-Pfade zunächst kompatibel halten; konkrete API-Versionierung und spätere Entfernung alter Aliase separat entscheiden.
- Keine produktiven Secrets oder weitreichenden Supabase-Service-Schlüssel in generierte Dateien, Logs oder Repository-Dateien schreiben.

## Refactoring in geordneten Batches

Jeder Batch endet mit gezielten Tests, Deployment-/VM-Auswirkungsprüfung und einer Aktualisierung dieses Plans. Ein Batch wird nicht als erledigt markiert, bevor sein überprüfbares Ergebnis und die Rollback-Auswirkung festgehalten sind.

### Batch 0 – Ist-Vertrag und sichere Testbasis

- Alle tatsächlich verwendeten REST-Pfade, HTTP-Methoden, Request-/Response-Beispiele und Authentifizierungsvarianten erfassen; Abweichungen zwischen Code und README korrigieren.
- Discord-Kommandos, Subcommands, Options, Defaults, Rollen-/Berechtigungsprüfungen und destruktive Aktionen aus JSON, Handlern und Tests zusammenführen.
- Aktuelle Verhaltenstests für Antworten, Fehlercodes, Defaults, Autorisierung und Discord-Interaktionen ergänzen, ohne Live-Cloud-Ressourcen zu verändern.
- Das AWS-Eventformat, Lambda-Paketlayout, Function-URL-/CloudFront-Routing und produktive Deploy-Reihenfolge verifizieren.
- Supabase-Enums und deren Verwaltung inventarisieren; eine sichere Quelle und Zugangsmethode für CI bestimmen.
- **Abnahmekriterium:** dokumentierter Ist-Vertrag, sichere gezielte Testbasis und bestätigte Event-/Schemaquellen; keine Änderung des Produktverhaltens.

### Batch 1 – API-Schemas und fachliche Operationsliste

- Request-/Response-Typen und Fehlerformat je Bereich festlegen.
- Fachliche Operationen und Regeln aus `rest_api.py`/`commands/` herausarbeiten; zunächst bestehende Regeln bewahren.
- API-Methoden, bestehende Pfad-Aliase und Autorisierungsgrenzen vertraglich testen.
- Noch keine Discord-Registrierung auf die neue Definition umstellen.
- **Abnahmekriterium:** getestete, nachvollziehbare API-Contracts und dokumentierte Kompatibilitätsmatrix.

### Batch 2 – Package-Grundgerüst und dünne API-Transportebene

- Neues Python-Package einführen und Konfiguration/Imports schrittweise migrieren.
- FastAPI-App, Middleware, Auth-Abhängigkeiten und Pydantic-Schemas ergänzen.
- Mangum-/Lambda-Integration mit dem produktiven Eventpfad erproben; bestehende HTTP- und Discord-Einstiege während Übergang getrennt halten.
- Deploymentpaket, Handler-Einstellung, lokale Tests und CI gemeinsam umstellen.
- **Abnahmekriterium:** bestehende REST-Contracts laufen durch den neuen Adapter; Lambda-Paket kann reproduzierbar gebaut und getestet werden.

### Batch 3 – Gemeinsame Anwendungsfälle und Integrationen

- Server-, Whitelist-, Account-, Billing- und DNS-Logik in nach Bereich organisierte Anwendungsfälle überführen.
- Hetzner/Supabase/GoDaddy/Mojang/VM-Agent-Zugriffe in Integrationsmodule kapseln.
- Rest-Routen werden dünne Adapter, die Eingaben validieren, Anwendungsfälle aufrufen und Ergebnisse abbilden.
- Veraltete interne REST-Handler erst entfernen, wenn keine Aufrufer mehr existieren und Vertragstests bestehen.
- **Abnahmekriterium:** keine duplizierte Geschäftsregel zwischen REST und Anwendungsfällen; fokussierte Unit-Tests ohne Netzwerk.

### Batch 4 – Supabase-Enum-Snapshot und Validierung

- Nach Klärung in Batch 0 die tatsächliche Enum-Quelle und CI-Berechtigung festlegen.
- Generator/Synchronisierung implementieren, Snapshot-Schema definieren, Deploymentfehler bei fehlgeschlagener oder inkompatibler Synchronisierung sicherstellen.
- Enum-Typen in API-Validierung und passende Discord-Choices integrieren; Werte mit Supabase abgleichen.
- Abweichungen oder inkompatible Änderungen als Review-blockierende Buildfehler ausweisen.
- **Abnahmekriterium:** jedes verwendete Enum ist auf DB-Quelle und Release-Snapshot zurückführbar; kein veralteter Fallback wird stillschweigend ausgeliefert.

### Batch 5 – API-gesteuerte Discord-Definitionen

- Discord-Metadaten/Mapping an den API-Vertrag anbinden und den Discord-Payload-Generator implementieren.
- Discord-Optionen mit denselben Pydantic-/Anwendungsregeln validieren; Discord-Berechtigungen und fachliche Autorisierung getrennt prüfen.
- Vor der Umschaltung alte und generierte Registrierungsdefinitionen vergleichen und Unterschiede prüfen.
- Hilfeansicht/Command-Cache aus derselben Quelle generieren; Discord-Limits und Autocomplete-Fälle testen.
- Deployment-Reihenfolge festlegen: generieren und validieren, Commands registrieren, Lambda-Paket bauen/deployen. Fehler bei Registrierung müssen das Deployment sichtbar stoppen.
- **Abnahmekriterium:** kein unabhängig gepflegtes Commands-JSON als Quelle; alle registrierten Commands zeigen auf benannte API-Operationen und bestehen Mapping-/Schema-Tests.

### Batch 6 – VM-Agent und Deploymentpfade

- Nur falls sinnvoll, VM-Skripte in einen separaten Ordner verschieben.
- Bootstrap-Download-URLs, Dateinamen, Imports, Systemd-Units und Hot-Reload gemeinsam aktualisieren.
- Kompatibilität mit bereits laufenden VMs bzw. deren künftigem Reload-Verhalten prüfen; bestehende Volumes und Spielstände nicht verändern.
- **Abnahmekriterium:** frische VM-Bootstrap-Installation und Reload laden exakt die erwarteten Dateien; laufende Daten und Systemd-Verhalten bleiben erhalten.

### Batch 7 – Bereinigung, Kompatibilität und Dokumentation

- Alte Handler, doppelte Definitionen und temporäre Migrationsadapter nur nach Aufruf-/Deprecation-Prüfung entfernen.
- Entscheidung über API-Versionierung und Sunset-Datum für Legacy-Pfade dokumentieren.
- README-Istbeschreibung, Setup, Deployment, OpenAPI, Enum-Sync und Discord-Generierung an den ausgelieferten Code angleichen.
- Unit-Tests als Standard ausführen; Live-Cloud-E2E nur manuell mit ausdrücklich bestätigter Umgebung/Ressourcenfreigabe.
- **Abnahmekriterium:** dokumentierte Zielstruktur entspricht Code und Deployment; alle ausgewählten Tests sind bestanden; verbleibende Risiken/Legacy-Schnittstellen sind benannt.

## Bug- und Feature-Backlog

Dieser Backlog hält gemeldete Probleme und gewünschte Verbesserungen fest, die bei der Refaktorierung oder in späteren Batches geprüft werden sollen. Ein Eintrag gilt erst als **verifiziert**, wenn Ursache und betroffene Komponenten untersucht und reproduzierbar dokumentiert wurden. Die hier beschriebenen Symptome stammen teilweise aus Nutzerbeobachtungen und sind noch keine Root-Cause-Analyse.

Statuswerte: **Gemeldet** = noch zu untersuchen; **Geplant** = einem Batch zugeordnet, aber nicht umgesetzt; **In Arbeit** = aktive Umsetzung; **Erledigt** = Änderung und Prüfung dokumentiert. Prioritäten sind vorläufig und können nach der Analyse angepasst werden.

### Bugs / technische Probleme

| ID | Prio | Status | Beobachtung / erwartetes Verhalten | Nächster Schritt und Zuordnung |
| --- | --- | --- | --- | --- |
| BUG-001 | Hoch | Gemeldet | Wird eine VM ohne `/stop` beendet, bleibt der zugehörige Serverdatensatz in Supabase offenbar auf `online`. Erwartet wird, dass ein ungeplanter/anderweitig ausgelöster Shutdown den Datenbankstatus zuverlässig aktualisiert. Ein regulärer `/stop`-Pfad allein genügt nicht als Lifecycle-Garantie. | Lifecycle- und Crash-Pfade in VM-Agent, Lambda und Hetzner untersuchen; idempotentes Offline-Update samt erreichbarer Retry-/Recovery-Strategie definieren. Startet in Batch 0 (Reproduktion/Tests), Implementierung in Batch 3 oder 6 je nach Ursache. |
| BUG-002 | Hoch | Gemeldet | Bei einem Shutdown ohne `/stop` wird der GoDaddy-DNS-Eintrag offenbar nicht auf `0.0.0.0` zurückgesetzt. Gleichzeitig wird in Supabase ein anderer DNS-Zustand beobachtet. Zielentscheidung des Nutzers: GoDaddy ist für tatsächlich veröffentlichte DNS-Records die maßgebliche Quelle der Wahrheit; Supabase soll keinen Erfolg behaupten, den GoDaddy nicht bestätigt hat. | Status- und Fehlerpfade beider Systeme getrennt nachvollziehen; Reihenfolge, Antwortprüfung und Retry/Abgleich festlegen. Keine Annahme treffen, dass Supabase hier tatsächlich synchron oder autoritativ ist. Mit BUG-003 gemeinsam in Batch 0 analysieren; Korrektur über DNS-Integration/Lifecycle in Batch 3 bzw. 6. |
| BUG-003 | Mittel | Gemeldet | Supabase enthält bei der Synchronisierung aus GoDaddy offenbar nicht alle DNS-Records; laut Beobachtung fehlt ungefähr die Hälfte, darunter insbesondere TXT-Records. Diese Records sind für die aktuellen Server möglicherweise nicht nötig, können aber später relevant sein. | GoDaddy-Antwortseiten, Paging, unterstützte Record-Typen, Filter und Supabase-Schema vergleichen. Zunächst Vollständigkeit für alle Record-Typen (insbesondere TXT) erfassen, bevor das Ziel-Schema oder der Sync geändert wird. Batch 0 Analyse, DNS-Integration und Contract-Tests in Batch 3. |
| BUG-004 | Niedrig | Gemeldet | Die Discord-Help-Ausgabe wird wegen der Discord-Längenbegrenzung in zwei Nachrichten gesplittet, aber der Umbruch liegt nicht an einer natürlichen Abschnittsgrenze. | Antwortsegmentierung so gestalten, dass zuerst an Absatz-/Abschnittsgrenzen unter dem Discord-Limit getrennt wird; bei langen Einzelabschnitten weiterhin sicher aufteilen. Im Zuge der Discord-Response-Arbeit (Batch 5/7) testen. |

### Feature Requests / geplante Verbesserungen

| ID | Prio | Status | Wunsch / Ziel | Geplante Einordnung |
| --- | --- | --- | --- | --- |
| FEAT-001 | Mittel | Geplant | Gleichzeitige Log-Streams verschiedener Server überlappen in Discord. Prüfen, ob ein Discord-Forum-Kanal mit einem Thread/Forum-Post pro Server die Logs sauber trennt. | Architektur-/Berechtigungsprüfung vor Umsetzung: Forum-Kanal und Threads anlegen/finden, parallele Stream-Zuordnung je Server, bestehende Threads archivieren/wiederverwenden sowie Discord-Ratenlimits und Fehler behandeln. Benötigte Bot-Rechte und Fallback-Kanal klären. Nicht Bestandteil des API-Struktur-Batches an sich; eigener Discord-Logging-Batch nach Stabilisierung der Log-Adapter. |
| FEAT-002 | Hoch | Geplant | Beim Serverstart sollen relevante Startprozesse nachvollziehbar geloggt werden: Bootstrap, Docker, Minecraft-Server, Control API, Lifecycle Guard und weitere relevante Dienste. Wenn möglich, soll die Log-Übertragung bzw. Verbindung zur Steuerung früh verfügbar sein. | Startphasen und Abhängigkeiten inventarisieren. Logging-Transport so früh wie sicher möglich initialisieren, aber nicht vor Netzwerk, Secrets und benötigter Laufzeitumgebung; Startfehler des Log-Streamers dürfen nicht unbemerkt bleiben. Bootstrap-Ausgaben benötigen einen eigenen frühen Erfassungspfad, da der spätere VM-Agent noch nicht läuft. Reihenfolge, Persistenz/Buffer bei Netzwerkausfall und Shutdown-Verhalten mit VM-Agent-Batch (6) planen und testen. |
| FEAT-003 | Mittel | Geplant | Discord-Logmeldungen sollen übersichtlicher sein und ihre Quelle (z. B. Bootstrap, Docker, Minecraft, Control API, Lifecycle Guard) schnell erkennen lassen. | Gemeinsames Log-Ereignisformat mit Quelle, Server, Zeit und Level definieren; Discord-Formatierung und Nachrichtenlängen/Ratenlimits berücksichtigen. Zusammen mit FEAT-001/002, nachdem Herkunft und Stream-Routing zuverlässig sind. |
| FEAT-004 | Mittel | Geplant | Alle Discord-Commands sollen künftig englische Namen/Bezeichnungen verwenden. | Discord-Namen sind öffentliche Schnittstellen: Umbenennungen müssen als registrierte Command-Änderungen geplant werden. Englische Command-Namen, Beschreibungen, Optionen und Help-Ausgabe mit Command-Generator/Migration in Batch 5 umstellen und prüfen; bestehende Commands während Rollout berücksichtigen. |
| FEAT-005 | Hoch | Geplant | Projektsprache soll Englisch werden: Code-Kommentare, Discord-Benachrichtigungen und -Antworten, Logs, README-/Entwicklertexte und sonstige nutzer-/entwicklerseitige Textinhalte. | Englisch wird die kanonische Sprache für neue und migrierte Texte. In Bereichen/Batches inkrementell übersetzen und Dokumentation nachziehen; keine Geschäftslogik nebenbei ändern. Externe Provider-/Spielausgaben dürfen unverändert durchgereicht werden. Spätere zusätzliche Übersetzungen wären eine separate Produktentscheidung. |
| FEAT-006 | Hoch | Geplant | Discord-Commands sollen genau dieselben Enums wie die normale API verwenden. | Bereits im Zielentwurf berücksichtigt: Supabase-Enum-Snapshot → API-Typen/Validierung → Discord-Choices bzw. Autocomplete aus derselben Quelle. In Batch 4 die Enum-Synchronisierung und Konsistenztests liefern; Batch 5 verwendet diese Typen im Generator. Discord-Limits (z. B. maximal 25 statische Choices) berücksichtigen, ohne Werte still zu entfernen. |
| FEAT-007 | Mittel | Geplant | Vorgegebene/feste Textinhalte sollen in JSON-Dateien abgelegt werden, damit Python-Handler übersichtlicher bleiben. | Wiederverwendbare, statische Texte wie Discord-Antwortvorlagen, Benachrichtigungen und ggf. lokalisierbare Texte in validierte JSON-Ressourcen auslagern; strukturierte Command-/Help-Metadaten aus dem API-Vertrag generieren. Keine pauschale Umwandlung aller Dateien: README, Quellcode, Skripte und notwendige Konfiguration bleiben in ihren passenden Formaten. JSON-Dateien müssen Schema-/Ladefehler sichtbar melden und werden mit Paketierung/Tests in Batch 5/7 abgesichert. |

### Verbindliche Sprach- und Textdaten-Entscheidungen

- **Englisch ist das Ziel für kanonische Projekttexte.** Die Umstellung erfolgt schrittweise; in jedem berührten Bereich wird die README-Dokumentation mit dem tatsächlich migrierten Stand aktualisiert. Ein vollständiger Übersetzungs-Batch wird eingeplant, statt Übersetzungen unkoordiniert über Refactoring-Änderungen zu verteilen.
- **Discord-Commands und API-Enums haben eine gemeinsame Quelle.** Discord-Choices und API-Validierung werden aus denselben versionierten/aktualisierten Werten abgeleitet. Der Supabase-Snapshot-Prozess aus „Supabase-Enums als API- und Discord-Verträge“ bleibt dafür Voraussetzung.
- **Feste Texte werden dort ausgelagert, wo es Übersicht und Wiederverwendung verbessert.** Für user-facing Texte wird JSON mit klaren Schlüsseln und Tests geprüft; nicht jeder Text und nicht jede Textdatei wird zwangsläufig JSON.
- **Die README bleibt die Projekt-Arbeitsdokumentation.** Nach jedem abgeschlossenen Batch werden Status, Änderungen am Plan, relevante Entscheidungen und offene Folgearbeiten ergänzt; erledigte Backlog-Einträge werden nicht kommentarlos entfernt, sondern mit Ergebnis/Datum im Änderungsprotokoll nachvollziehbar gemacht.

## Offene Entscheidungs- und Prüfstellen

Diese Punkte werden nicht stillschweigend entschieden:

1. Welche Supabase-Projekt-/DB-Schemaquelle ist maßgeblich: versionierte Migrationen, direkter read-only PostgreSQL-Zugang oder ein eng begrenzter Metadaten-RPC?
2. Welcher sichere CI-Zugang darf Enum-Metadaten während jedes Deployments abrufen, und soll der generierte JSON-Snapshot nur im Release-Paket oder zusätzlich versioniert vorliegen?
3. Welche bestehenden REST-Pfade/Methoden werden von externen Clients tatsächlich genutzt, und soll nach der kompatiblen Migration eine API-Version im Pfad eingeführt werden?
4. Welche Discord-Befehle sollen bei Schemaänderungen automatisch global registriert werden, und soll die Registrierung bei jedem Deployment oder nur bei relevanten Änderungen laufen?
5. Welche server-/userbezogenen Rechte sind verbindlicher Vertrag für REST-Clients? Der bestehende gemeinsame `AUTH_SECRET` identifiziert keinen individuellen Nutzer; ein vom Client gesendetes `discord_user_id` ist keine eigenständige Authentifizierung.
6. Soll die Serverlöschoperation künftig eine laufende VM stoppen, oder bleibt das aktuell dokumentierte Verhalten bestehen? Diese potenziell destruktive Geschäftsregel wird vor einer Verhaltensänderung ausdrücklich bestätigt.
7. Welche Art von GoDaddy-Synchronisierung soll als maßgeblich gelten (einseitiges Lesen, gezieltes Schreiben oder bidirektionaler Abgleich), und wie sollen externe Änderungen, nicht unterstützte Record-Typen und API-Fehler behandelt werden?
8. Für Discord-Log-Threads: existiert bereits ein geeigneter Forum-Kanal, und soll der Bot ihn verwalten dürfen (Forum-Post/Thread erstellen, umbenennen und archivieren)?
9. Welche Startphasen müssen zwingend live gestreamt werden, und welche dürfen bei noch nicht verfügbarer Verbindung lokal gepuffert bzw. später übertragen werden?

## Änderungsprotokoll

| Datum | Batch / Änderung | Ergebnis und aktualisierte Entscheidungen |
| --- | --- | --- |
| 2026-10-08 | Plan angelegt | Noch keine Implementierung. API-first-Ziel, Generator für Discord-Commands, Supabase-Enum-Snapshot pro Deployment und gestufte Migration aufgenommen. Enum-Quelle, Zugriff und Snapshot-Versionierung bleiben bis zur Ist-Prüfung offen. |
| 2026-10-08 | Bug-/Feature-Backlog ergänzt | BUG-001 bis BUG-004 und FEAT-001 bis FEAT-007 als gemeldet/geplant aufgenommen. Keine Umsetzung oder Root-Cause-Bestätigung; Offline-/DNS-Probleme und Screenshot-Beobachtung müssen in Batch 0 reproduziert und analysiert werden. Englische Projektsprache, JSON-Ressourcen und gemeinsame API-/Discord-Enums als Refactoring-Ziele ergänzt. |
