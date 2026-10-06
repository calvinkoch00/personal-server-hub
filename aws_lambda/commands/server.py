import os
import re
import json
import urllib.request
from services import hetzner


def handle_status(body: dict, data: dict) -> str:
    servers = hetzner.list_servers()
    if not servers:
        return "⚪ Es läuft aktuell kein Server."
    lines = [
        f"• `{s['name']}` (ID: {s['server_id']}) — `{s.get('status', 'unknown')}` — IP: `{s['ip']}`"
        for s in servers
    ]
    return "🟢 **Aktive Server:**\n" + "\n".join(lines)


def handle_stop(body: dict, data: dict) -> str:
    servers = hetzner.list_servers()
    if not servers:
        return "⚪ Kein laufender Server zum Stoppen vorhanden."

    target = servers[0]
    target_ip = target.get("ip")
    target_id = str(target.get("server_id"))

    try:
        if hasattr(hetzner, "trigger_server_graceful_stop"):
            hetzner.trigger_server_graceful_stop(target_ip, target_id)
        else:
            auth_secret = os.environ.get("AUTH_SECRET", "")
            req = urllib.request.Request(
                f"http://{target_ip}:8080/stop",
                data=b"{}",
                headers={"Content-Type": "application/json", "x-auth-token": auth_secret},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
        return f"🛑 **Shutdown für `{target['name']}` eingeleitet.** (Container sichern & VM löschen)"
    except Exception:
        hetzner.delete_server(target_id)
        return f"🛑 **Server `{target['name']}` direkt via Hetzner-API gelöscht.**"


def handle_start(body: dict, data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    game = str(options.get("game", "minecraft")).strip().lower()
    duration_raw = str(options.get("duration", "5m")).strip().lower()

    log_mode = str(options.get("log", "none")).strip().lower()
    if log_mode in ["true", "1"]:
        log_mode = "game"
    elif log_mode in ["false", "0"]:
        log_mode = "none"

    unit_map = {"m": 60, "h": 3600, "d": 86400}
    readable_map = {"m": "Minute(n)", "h": "Stunde(n)", "d": "Tag(e)"}

    match = re.match(r"^(\d+)\s*([mhd])$", duration_raw)
    if match:
        val, unit = int(match.group(1)), match.group(2)
        seconds = val * unit_map[unit]
        readable = f"{val} {readable_map[unit]}"
    else:
        seconds = 300
        readable = "5 Minute(n)"

    try:
        res = hetzner.create_server(
            game=game,
            seconds=seconds,
            readable=readable,
            server_type="cpx32",
            enable_logging=log_mode
        )
        addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
        log_labels = {"none": "⚪ Aus", "game": "🎮 Nur Game", "all": "📡 Alles (Game + System)"}
        return (
            f"🟡 **Hardware wird hochgefahren!**\n"
            f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
            f"🌐 **Adresse:** {addr}\n"
            f"⏳ **Laufzeit:** {readable}\n"
            f"📋 **Live-Logs:** {log_labels.get(log_mode, log_mode)}\n\n"
            f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
        )
    except Exception as e:
        return f"❌ Fehler beim Starten des Servers: {e}"


def handle_log(body: dict, data: dict) -> str:
    servers = hetzner.list_servers()
    if not servers:
        return "⚪ Kein aktiver Server online."

    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    mode = str(options.get("mode", "game")).strip().lower()
    target_ip = servers[0].get("ip")
    try:
        auth_secret = os.environ.get("AUTH_SECRET", "")
        payload = json.dumps({"mode": mode}).encode("utf-8")
        req = urllib.request.Request(
            f"http://{target_ip}:8080/toggle-log",
            data=payload,
            headers={"Content-Type": "application/json", "x-auth-token": auth_secret},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            res_data = json.loads(resp.read().decode())
            cur_mode = res_data.get("mode", mode)
            return f"📡 **Live-Logs wurden umgestellt auf: `{cur_mode.upper()}`**"
    except Exception as e:
        return f"⚠ Agent auf VM nicht erreichbar: {e}"