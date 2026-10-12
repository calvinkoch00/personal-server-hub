# On-Demand Gaming & Workload Server Hub

Serverlose Steuerungs-Infrastruktur zur On-Demand-Bereitstellung, Verwaltung und automatischen Terminierung von Gameservern in der Hetzner Cloud. Gesteuert via Discord Slash-Commands oder REST-API über AWS CloudFront, AWS Lambda, GoDaddy DNS, Supabase-Persistenz und modulare Systemd-Dienste auf persistentem Block-Storage.

---
## Start hier (Übergabe an den nächsten Agenten)

Stand: 2026-10-12, Branch `staging`. Dieses Kapitel fasst den aktuellen Zustand zusammen; Details stehen in den Kapiteln darunter und im Änderungsprotokoll. **Bei Widersprüchen gilt der Code.**

### Architektur-Status (FastAPI Migration V2 - Vollständig Abgeschlossen)

Die Migration aller REST-Endpunkte und des Discord-Adapters auf die moderne Schichtenarchitektur ist abgeschlossen:
**FastAPI-Router (`api/routers/`) → Pydantic-Schema (`api/schemas/`) → Anwendungslogik (`application/`)**.

- **FastAPI & Endpunkte:** Alle Bereiche (Billing, Whitelist, Server-Lifecycle, DNS, Users, Game Accounts) sind vollständig migriert und über FastAPI angebunden.
- **Zentrale Validierung:** Sämtliche Eingabevalidierung (inkl. Slug-Formatierung und Typen) erfolgt ausschließlich in den Pydantic-Schemas (`api/schemas/`). Die Supabase-Datenbank enthält keine geschäftlichen Prüfregeln (Constraints beschränken sich auf `NOT NULL` und Fremdschlüssel).
- **Discord-Adapter:** Discord ruft die FastAPI-App direkt im selben Prozess über `internal_headers` auf (kein öffentlicher HTTP-Umweg).
- **Authentifizierung:** Globales `get_principal` sowie Rollenprüfungen (`require_registered`, `require_admin`) via `api/dependencies.py` aktiv.
- **Code-Cleanup:** Veraltete Module wie `rest_api.py`, `services/` und `commands/` wurden entfernt.

### Authentifizierungsmodell (`api/dependencies.py`)

- `get_principal` ist global registriert (`FastAPI(dependencies=[Depends(get_principal)])`); jede Route verlangt eine gültige Identität.
- **Service-Principal:** gültiges `AUTH_SECRET` als `x-auth-token` oder `Authorization: Bearer`.
- **Discord-Principal:** Header `x-internal-token` (zufälliger, prozessinterner `INTERNAL_TOKEN`) plus `x-discord-user-id`. `internal_headers(user_id)` baut diese Header. Der Token kann von außen nicht erraten werden; der Discord-Adapter darf ihn erst nach erfolgreicher Signaturprüfung setzen.
- `require_registered`: Service-Aufrufer passieren; ein Discord-Nutzer muss in `dim_users` existieren, sonst 403.
- `require_admin`: nur ein Discord-Nutzer mit Rolle `superadmin`. `AUTH_SECRET` allein ergibt 403; ein fehlgeschlagener Rollen-Lookup ergibt 502. (`superadmin` ist die einzige globale Admin-Rolle, die der bestehende Code als Admin behandelt; `server-admin` bleibt eine Prüfung pro Server in Whitelist-/Server-Logik. **Vom Nutzer nicht ausdrücklich bestätigt.**)
- `get_user_role` liegt in `application/users.py`.

### Entscheidungen des Nutzers

- Discord ruft die App im selben Prozess auf.
- Unregistrierte Discord-Nutzer dürfen nur `/users/register`, `/help` und `addgameaccount` verwenden.
- Admin-only-Routen verlangen einen Discord-Admin; `AUTH_SECRET` reicht nicht.
- Akzeptierte Verhaltensänderungen, sobald `rest_api.py` entfernt ist: das Body-Feld `action` funktioniert nicht mehr, unbekannte Pfade liefern FastAPIs 404-Body, falsche Methoden 405, ungültige Eingaben 422.
- FEAT-008: Cooldown ignorieren und nicht speichern.

### Entwickeln und testen

```bash
cd src && python3 -m pytest -q    # Stand: 104 Tests grün
```

- `tests/unit/test_auth.py` ist ein Vertragstest über alle Routen aus `app.openapi()`. Grund: FastAPI 0.143 listet eingebundene Router nicht in `app.routes`.
- `tests/unit/api/conftest.py` überschreibt die Authentifizierung für Router-Unit-Tests.
- HTTP-Client-Paket ist `httpx2` (Import `httpx2`). **Nicht geprüft**, ob dessen ASGI-Transport synchrone In-process-Aufrufe unterstützt; Starlettes `TestClient` funktioniert in den bestehenden Tests. Vor dem Discord-Adapter klären.
- `scripts/run_user_tests.py` greift auf Live-Ressourcen zu und läuft nicht im normalen Testlauf.

### VM-Agent

Skripte liegen in `/opt/gameserver-agent/`; Dienste: `gameserver-{logs,tracker,control,guard}.service`; Secrets in `/mnt/gamespeicher/secrets.env`. Die Skripte kommen von `<GITHUB_REPO_RAW>/src/vm_agent/` (Fix `5a1c5bf`). Die Staging-VM `server-minecraft-test-2` wurde mit dem alten `bootstrap.sh` angelegt und hat ein leeres Agent-Verzeichnis; Wiederherstellung: die vier Skripte manuell per `curl` laden und `pip3 install` ausführen. Ob das geschehen ist, ist unbekannt.

### Nicht verifiziert

- Nichts wurde live gegen Lambda, GoDaddy, Supabase oder eine echte VM getestet.
- Deploy- und GitHub-Actions-Status der Commits `885e1bc`, `5a1c5bf`, `e03f4f6` ist ungeprüft.
- Der Wert von `GITHUB_REPO_RAW` in Staging (muss auf `/staging` enden) ist ungeprüft.

### Offene Punkte

- Nutzt ein Client andere Methoden als GET/POST auf `/dns/records` oder `/dns/sync` (jetzt 405)?
- Produktfrage zur GoDaddy-Sync-Richtung (siehe Offene Entscheidungs- und Prüfstellen, Punkt 7; BUG-002/003).
- BUG-005 (doppelte/verspätete Starts/Stops) könnte mit asynchronen Lambda-Retries zusammenhängen (unbestätigt). Günstiger Test: `MaximumRetryAttempts=0` am Worker.
- Alias `handle_addgameaccount` in `rest_api.py` wird von `route_request` und drei Tests in `test_mojang.py` genutzt.

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
* `gameserver-logs.service` (`log_streamer.py`): Pufferung und Übertragung von Konsolen- und Systemlogs per Discord Webhook (drei Modi: `none`, `game`, `all`).
* `gameserver-control.service` (`control_api.py`): Lokaler HTTP-Endpunkt auf Port 8080 für Remote-Steuerung (`/stop`, `/toggle-log`, `/emit-log`).
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

Aktuell enthält `src/personal_server_hub/config.py` nur eine Spielkonfiguration für Minecraft. Obwohl einige Befehle ein `game`-Feld anbieten, ist daraus keine Unterstützung weiterer Gameserver-Images abzuleiten; das Bootstrap-Skript erstellt derzeit nur ein Minecraft-Compose-Setup.

---

## REST Control Plane API

Die konfigurierte öffentliche API-Basis ist `https://api.calvinkoch.ch`. `GET /help`, `GET /users/{discord_user_id}`, `POST /game-accounts`, `POST /users/register`, `GET /dns/records` und `POST /dns/sync` werden von der FastAPI-Anwendung in `src/personal_server_hub/api/` bedient; die übrigen bestehenden Pfade werden vorerst weiterhin in `src/personal_server_hub/rest_api.py` geroutet. `/addgameaccount` und `POST /game-accounts` prüfen zuerst den Discord-Nutzer in `dim_users`; falls er nicht gefunden wird, wird er registriert und anschließend der Spielaccount verknüpft. `POST /users/register` registriert oder aktualisiert nur den Discord-Nutzer in `dim_users`, während `GET /users/{discord_user_id}` den Nutzer nach Discord-ID abruft. Diese authentifizierten REST-Endpunkte sind keine Discord-Slash-Commands. Die Lambda-Funktion prüft bei regulären REST-Anfragen den Token, verarbeitet `OPTIONS` für CORS und erwartet JSON für Requests mit Body.

`GET /help` liefert die Hilfebeschreibung als JSON unter dem Feld `help`. `GET /users/{discord_user_id}` liefert `discord_user_id` und `discord_username` oder HTTP 404, falls der Nutzer fehlt. `POST /game-accounts` erwartet `discord_user_id`, `discord_username`, `game` und `username`. `POST /users/register` erwartet `discord_user_id` und `discord_username` (optional, Standardwert `Unknown`). Alle Routen verlangen wie die übrigen REST-Endpunkte einen gültigen Authentifizierungstoken.

### Authentifizierung

Jede reguläre REST-Anfrage verlangt einen gültigen Token. Unterstützt werden `x-auth-token`, `X-Auth-Token` oder `Authorization: Bearer $AUTH_SECRET`. Discord-Interaktionen verwenden stattdessen `x-signature-ed25519` und `x-signature-timestamp`, geprüft mit `DISCORD_PUBLIC_KEY`.

| Header-Feld | Beschreibung |
| --- | --- |
| `x-auth-token` / `X-Auth-Token` | Konfiguriertes `AUTH_SECRET`. |
| `Authorization` | Alternativ `Bearer $AUTH_SECRET`. |
| `Content-Type` | Für Requests mit JSON-Body: `application/json`. |

Die migrierten Routen (siehe „Start hier“) erzwingen ihre HTTP-Methode in FastAPI. Die übrigen Routen werden noch von `rest_api.py` nach Pfad bzw. bei der Root-URL nach `action` ausgewählt, ohne Methodenprüfung; die Beispiele unten verwenden `POST`. Zusätzlich gilt das Principal-Modell aus „Start hier“ (`AUTH_SECRET` oder interner Discord-Principal).

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

`src/vm_agent/bootstrap.sh` lädt die Agent-Skripte von `<GITHUB_REPO_RAW>/src/vm_agent/<script>` zur VM nach `/opt/gameserver-agent/` und bricht bei einem fehlgeschlagenen Download ab. Der Branch ergibt sich aus dem Secret `GITHUB_REPO_RAW` (Staging muss auf `/staging` enden). Das Hetzner-Volume wird nach `/mnt/gamespeicher` gemountet und enthält persistente Daten:

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

`setup_env.sh` erstellt `.venv`, installiert `requirements.txt` und richtet VS Code/Pylance ein. Es erzeugt keine `.env` und provisioniert keine Cloud-Ressourcen. Lege lokale Secrets bei Bedarf selbst in `.env` ab; `.env` ist in `.gitignore` enthalten. `src/scripts/register_discord_commands.py` benötigt `DISCORD_APPLICATION_ID` und `DISCORD_BOT_TOKEN` (aus der Umgebung oder `.env`).

Die bereitgestellte [`.env.example`](./.env.example) enthält Beispielwerte für Hetzner, Authentifizierung und eine Lambda Function URL. Für die Discord-Command-Registrierung müssen zusätzlich folgende Werte lokal gesetzt sein:

```env
DISCORD_APPLICATION_ID=deine_discord_application_id
DISCORD_BOT_TOKEN=dein_discord_bot_token
```

### 2. Bitwarden als Quelle der Wahrheit

Die GitHub Actions Workflow-Datei [`.github/workflows/deploy.yml`](./.github/workflows/deploy.yml) liest die benötigten Einträge über die offizielle Bitwarden Secrets Manager Action. Bitwarden bleibt der Ort, an dem Anwendungswerte gepflegt werden. Die Workflow-Datei referenziert die Bitwarden Secret IDs; sie enthält keine Werte.

Ein Bitwarden-Machine-Account-Token kann nicht zuerst aus Bitwarden abgerufen werden, weil genau dieses Token den Zugriff auf Bitwarden ermöglicht. Lege deshalb einmalig in GitHub unter **Settings → Secrets and variables → Actions → Secrets** das Secret `BW_ACCESS_TOKEN` an. Kopiere den Access Token direkt aus Bitwarden nach GitHub; nicht in den Quellcode, ein Workflow-Log oder einen Chat. Der Machine Account benötigt nur Lesezugriff auf das Projekt mit den in der Workflow-Datei aufgelisteten Einträgen.

Der Workflow synchronisiert diese Lambda-Werte als ein JSON-Secret nach AWS Secrets Manager:

* `AUTH_SECRET`
* `DISCORD_APPLICATION_ID`
* `DISCORD_LOG_WEBHOOK_URL`
* `DISCORD_PUBLIC_KEY`
* `DISCORD_STATUS_WEBHOOK_URL`
* `GITHUB_REPO_RAW`
* `GODADDY_API_KEY`, `GODADDY_API_SECRET`, `GODADDY_DOMAIN`
* `HETZNER_API_TOKEN`
* `SUPABASE_KEY`, `SUPABASE_URL`

`DISCORD_BOT_TOKEN` wird nur beim Registrieren der Discord-Slash-Commands im Workflow verwendet und **nicht** in das Lambda-Runtime-Secret kopiert. `AWS_REGION` wird im Workflow aus Bitwarden für AWS-Aufrufe genutzt; in Lambda stellt AWS die Region als reservierte Laufzeitvariable bereit. `GODADDY_SUBDOMAIN` und `HETZNER_LOCATION` sind keine Lambda-Umgebungswerte mehr: Subdomains werden für Server anhand der Verknüpfung über `server_id` aus `dim_dns_records` gelesen. Fehlt ein verknüpfter DNS-Eintrag, ist der Fallback `<game>-default` für den Default-Server und der Server-Slug für Nicht-Default-Server. Der Serverstandort wird aus `dim_servers.hetzner_location` gelesen. Neu angelegte Server erhalten zunächst `nbg1`, gespeichert in `dim_servers`.

Die Bitwarden-Einträge `BWS_ACCESS_TOKEN`, `BWS_PROJECT_ID`, `GITHUB_TOKEN`, `LAMBDA_FUNCTION_URL` und `SUPABASE_PUBLIC_KEY` werden vom aktuellen Backend/Workflow nicht als Runtime-Konfiguration verwendet. Der Bitwarden Machine-Account-Token muss separat als GitHub Actions Secret `BW_ACCESS_TOKEN` vorliegen. Nicht verwendete Werte werden bewusst nicht in AWS kopiert.

### 3. GitHub Actions Zugriff auf AWS mit OIDC

GitHub erhält keine langfristigen AWS-Zugangsschlüssel. Der einmalige AWS-Rollout ist in [`infra/github-actions-oidc.yml`](./infra/github-actions-oidc.yml) beschrieben und richtet ein:

* eine eingeschränkte GitHub-OIDC-Rolle, die nur `calvinkoch00/personal-server-hub` auf `main` vertraut;
* das Secret `personal-server-hub/lambda-runtime` in Secrets Manager;
* `PutSecretValue` auf dieses Secret für die GitHub-Rolle;
* `GetSecretValue` auf dasselbe Secret für die bestehende Lambda Execution Role `hetzner-server-controller-role-iiub65qe`.

Prüfe in **IAM → Identity providers**, ob `https://token.actions.githubusercontent.com` bereits existiert. Wenn ja, setze den Template-Parameter `CreateGitHubOidcProvider` auf `false`; wenn nicht, bleibt er `true` und CloudFormation legt den Provider an. Erstelle den Stack in derselben AWS-Region, die in Bitwarden als `AWS_REGION` gepflegt wird. Prüfe vor dem Erstellen, dass die Lambda Execution Role im Template-Parameter exakt mit der Rolle unter **Lambda → Configuration → Permissions** übereinstimmt.

Nach erfolgreichem Stack-Deployment hinterlege unter GitHub **Settings → Secrets and variables → Actions → Variables** die CloudFormation Outputs:

* `AWS_DEPLOY_ROLE_ARN` = `GitHubActionsDeployRoleArn`
* `LAMBDA_RUNTIME_SECRET_ARN` = `LambdaRuntimeSecretArn`

Der Workflow benötigt außerdem das oben beschriebene GitHub Actions Secret `BW_ACCESS_TOKEN`. Danach synchronisiert er Bitwarden bei Pushes auf `main`, manuellem `workflow_dispatch` und täglich. Der tägliche Lauf übernimmt Änderungen an Bitwarden automatisch und aktualisiert die Lambda-Konfiguration, sodass neue Ausführungsumgebungen den aktuellen Secret-Stand laden.

Die IAM User `github-lambda-deployer` in den Screenshots ist kein OIDC-Role. Lass ihn bestehen, bis ein Push oder manueller Workflow-Lauf mit OIDC erfolgreich war. Danach können seine alten Access Keys widerrufen und der Benutzer entfernt werden, falls er sonst nicht verwendet wird.

### 3a. Staging mit eigener Lambda verbinden

Staging verwendet den separaten Workflow [`.github/workflows/deploy-staging.yml`](./.github/workflows/deploy-staging.yml) und das Template [`infra/staging-github-actions-oidc.yml`](./infra/staging-github-actions-oidc.yml). Der Workflow läuft nur bei Pushes auf `staging` oder einem manuellen Start. Seine IAM-Rolle vertraut nur dem Branch `staging` und darf nur die Funktion `personal-server-hub-api-staging` sowie das Runtime-Secret `personal-server-hub/staging/lambda-runtime` aktualisieren. Der Produktionsworkflow und seine AWS-Rolle bleiben davon getrennt.

1. Prüfe in derselben AWS-Region wie die Staging-Lambda (`eu-central-1`), ob der GitHub OIDC Provider bereits in IAM angelegt ist. Wenn ja, setze beim CloudFormation-Stack-Deployment `CreateGitHubOidcProvider` auf `false`; andernfalls auf `true`.
2. Erstelle aus dem Staging-Template einen separaten CloudFormation-Stack. Bestätige dabei, dass `LambdaFunctionName` und `LambdaExecutionRoleName` exakt zur Staging-Lambda bzw. ihrer Execution Role passen.
3. Lege die CloudFormation Outputs `StagingGitHubActionsDeployRoleArn` und `StagingRuntimeSecretArn` als Einträge `STAGING_AWS_DEPLOY_ROLE_ARN` und `STAGING_LAMBDA_RUNTIME_SECRET_ARN` in deinem `server-hub-staging` Bitwarden-Projekt ab. Trage ihre Bitwarden Secret IDs im Staging-Workflow ein. Damit bleiben auch diese Umgebungswerte in Bitwarden statt in GitHub Actions Variables.
4. Lege den staging-only Bitwarden Machine-Account-Token als GitHub Actions Secret `BW_STAGING_ACCESS_TOKEN` an. Der Machine Account darf nur das Staging-Projekt lesen. Die Secret-IDs im Workflow müssen ebenfalls aus diesem Staging-Projekt stammen. Dieser Token ist der Bootstrap-Ausnahmefall: GitHub benötigt ihn, um überhaupt Bitwarden abfragen zu können.
5. Prüfe in Bitwarden, dass `GITHUB_REPO_RAW` den Raw-Content-Basis-URL des Branches angibt, zum Beispiel `https://raw.githubusercontent.com/calvinkoch00/personal-server-hub/staging`. Der Bootstrap-Pfad wird im Code ergänzt. `DISCORD_BOT_TOKEN` wird nur zur Registrierung der Commands der Staging-Discord-App verwendet und nicht an Lambda übertragen.

Der Workflow synchronisiert nur die Staging-Einträge in das Staging-Secrets-Manager-Secret und liest auch die beiden AWS-Referenzwerte direkt aus Bitwarden. Die Supabase-URL ist im Staging-Workflow fest auf das Staging-Projekt `robyfwiyevnodmhdlkiq` gesetzt; nur der zugehörige Supabase-Key wird aus dem Staging-Bitwarden-Projekt geladen. Er fügt zusätzlich `DNS_SUBDOMAIN_PREFIX=staging-` hinzu: DNS-Schreib-/Löschvorgänge und DNS-Synchronisierung bleiben dadurch auf `staging-`-Records beschränkt. Nutze weiterhin ausschließlich ein Hetzner-Token des separaten Staging-Projekts. Der Workflow wurde nicht automatisch in AWS ausgerollt; der Stack muss erst in AWS erstellt werden.

### 4. Lambda Runtime-Konfiguration

Das Deployment packt `src/personal_server_hub/` zusammen mit den Abhängigkeiten. Der konfigurierte Handler lautet `personal_server_hub.lambda_function.lambda_handler`; ein Kompatibilitäts-Handler `lambda_function.lambda_handler` ist im Paket enthalten, damit der Code- und Handlerwechsel beim ersten Rollout ohne Unterbrechung möglich ist.

Der Workflow verwaltet die Lambda-Umgebungsvariablen `APP_SECRETS_ARN` und `SECRET_VERSION_ID`. Die Anwendung lädt beim Cold Start das JSON-Secret über die Lambda Execution Role und setzt die enthaltenen Anwendungswerte in der Prozessumgebung, bevor Anwendungsmodule importiert werden. Die Werte werden nicht geloggt. Entferne nach erfolgreichem Rollout alte, direkt in Lambda gespeicherte Anwendungs-Secretwerte; der Workflow ersetzt die Funktion-Umgebung auf `APP_SECRETS_ARN` und `SECRET_VERSION_ID`. AWS-eigene reservierte Variablen wie `AWS_REGION` und `AWS_LAMBDA_FUNCTION_NAME` bleiben AWS-managed.

Secrets Manager ist ein zusätzlicher AWS-Dienst mit laufenden Kosten pro Secret und API-Aufrufen; siehe [AWS Secrets Manager Pricing](https://aws.amazon.com/secrets-manager/pricing). Das Laufzeit-Secret enthält keine Discord-Bot-Credentials. Die Secrets werden im GitHub-Runner während des Syncs verarbeitet, aber nie absichtlich ausgegeben; Runner und Workflow-Code sind daher Teil der Sicherheitsgrenze.

`AWS_LAMBDA_FUNCTION_NAME` wird von AWS bereitgestellt; der Discord-Einstieg verwendet ihn für die asynchrone Selbstinvokation. Die Lambda Execution Role benötigt weiterhin `lambda:InvokeFunction` auf diese Funktion. Setze das Function-Timeout auf mindestens 30 Sekunden für Worker-Aufrufe zu Hetzner, Supabase und VM-Agent. Der synchrone Discord-Einstieg antwortet vorher mit Deferred ACK.

Die Minecraft-Code-Defaults sind Volume `107045799`, Port `25565` und Servertyp `cpx32`; Servermetadaten einschließlich `hetzner_location`, Volume und Servertyp werden für angelegte Server aus Supabase gelesen. `VOLUME_ID` aus der lokalen Beispielkonfiguration ist kein Lambda-Override.

### 5. Discord Interactions und Command-Registrierung

1. Im [Discord Developer Portal](https://discord.com/developers/applications) die Interactions Endpoint URL auf den öffentlichen HTTPS-Endpunkt der Lambda-API setzen (im beschriebenen Deployment `https://api.calvinkoch.ch`).
2. Den passenden Discord Public Key als `DISCORD_PUBLIC_KEY` in Bitwarden pflegen; der Deployment-Workflow synchronisiert ihn zu Lambda.
3. Global Slash Commands mit `DISCORD_APPLICATION_ID` und `DISCORD_BOT_TOKEN` registrieren:

```bash
source .venv/bin/activate
python src/scripts/register_discord_commands.py
```

Das Registrierungsskript liest die `PUT /applications/{application_id}/commands`-Antwort und aktualisiert daraus `src/personal_server_hub/commands_cache.txt`. Die Command-Definitionen kommen aus `src/scripts/discord_commands.json`.

---
