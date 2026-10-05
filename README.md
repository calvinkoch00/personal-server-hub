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

---

# Server Hub Control Plane API

Serverlose REST-Schnittstelle zur On-Demand-Bereitstellung und Steuerung von Hetzner Cloud Gameservern via AWS Lambda.

---

## Authentifizierung

Jeder Request an geschützte Endpunkte erfordert das Secret im HTTP-Header. Fehlt dieser oder ist ungültig, antwortet die API mit `401 Unauthorized`.

| Header-Feld                              | Typ        | Beschreibung                       |
| :--------------------------------------- | :--------- | :--------------------------------- |
| `x-auth-token` (oder `X-Auth-Token`) | `string` | Dein konfiguriertes`AUTH_SECRET` |
| `Content-Type`                         | `string` | `application/json`               |

---

## Endpunkte

### 1. Server starten

Erstellt eine neue VM in Hetzner Cloud, hängt das persistente Speicher-Volume ein und startet den Docker-Stack via `cloud-init`. Enthält zur Kostensicherung standardmäßig einen automatischen Selbstlöschungs-Mechanismus (20 Sekunden).

* **Methoden & Pfade:**
  * `POST /start`
  * `POST /` mit JSON-Body `{"action": "start"}`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

#### Request Body (optional)

```json
{
  "server_type": "cpx32"
}
```

*(Wird `server_type` weggelassen, wird standardmäßig `cpx32` mit 4 vCPUs und 8 GB RAM gewählt).*

#### Response (`200 OK`)

```json
{
  "message": "Server-Start initiiert",
  "discord_summary": "🎮 Server gestartet! IP: `123.45.67.89` (Laufzeit: 20s)",
  "data": {
    "server_id": 12345678,
    "status": "initializing",
    "ip": "123.45.67.89",
    "server_type": "cpx32",
    "auto_kill_after_seconds": 20
  }
}
```

---

### 2. Server-Status abfragen

Ermittelt den aktuellen Hardware- und Netzwerkstatus der Hetzner-VM anhand der übergebenen `server_id`.

* **Methoden & Pfade:**
* `GET /status?server_id=<SERVER_ID>`
* `POST /status` mit Body `{"server_id": "<SERVER_ID>"}`
* `POST /` mit Body `{"action": "status", "server_id": "<SERVER_ID>"}`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

#### Response (`200 OK`)

```json
{
  "data": {
    "server_id": 12345678,
    "status": "running",
    "ip": "123.45.67.89"
  }
}
```

---

### 3. Server stoppen & löschen

Fährt den Hetzner-Server vorzeitig herunter und löscht die Instanz. Das eingehängte Volume wird dabei automatisch getrennt (`Unattached`) und bleibt mit allen Daten unversehrt erhalten.

* **Methoden & Pfade:**
* `POST /stop`
* `POST /` mit JSON-Body `{"action": "stop", "server_id": "<SERVER_ID>"}`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

#### Request Body

```json
{
  "server_id": 12345678
}
```

#### Response (`200 OK`)

```json
{
  "message": "Server wird heruntergefahren",
  "discord_summary": "🛑 Server wurde gestoppt.",
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



### 4. Alle Server auflisten

Gibt eine Liste aller aktuell in Hetzner Cloud existierenden Server zurück. Ideal für Status-Widgets im Web-Dashboard oder Übersichts-Befehle im Discord-Bot.

* **Methoden & Pfade:**
  * `GET /servers`
  * `POST /servers`
  * `POST /` mit JSON-Body `{"action": "list"}`
* **Headers:** `x-auth-token: <AUTH_SECRET>`

#### Response (`200 OK`)

```json
{
  "message": "1 Server gefunden",
  "discord_summary": "🟢 Aktuell laufen 1 Server.",
  "data": [
    {
      "server_id": 12345678,
      "name": "minecraft-ondemand",
      "status": "running",
      "ip": "123.45.67.89",
      "server_type": "cpx32",
      "created": "2026-10-05T18:00:00Z"
    }
  ]
}
```

---

### 5. CORS Preflight

Wird automatisch von Browsern (z. B. deiner Angular Single-Page-Application) vor einem POST-Request gesendet.

* **Methode & Pfad:** `OPTIONS /*`
* **Response (`200 OK`):** Sendet CORS-Header (`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: *`) zurück.

---

## Status-Codes Übersicht

| Status               | Bedeutung                                                    |
| -------------------- | ------------------------------------------------------------ |
| `200 OK`           | Anfrage erfolgreich ausgeführt.                             |
| `400 Bad Request`  | Fehlende Pflichtfelder (z. B. keine`server_id` angegeben). |
| `401 Unauthorized` | Fehlender oder inkorrekter`x-auth-token`.                  |
| `404 Not Found`    | Unbekannter Pfad / unbekannte Action aufgerufen.             |
| `500 Server Error` | Interner Hetzner-API- oder Laufzeitfehler.                   |
