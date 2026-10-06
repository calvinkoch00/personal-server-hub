import os
import rest_api

def get_help_message() -> str:
    cache_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "commands_cache.txt")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    return (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/start` — Startet den Server (Felder: `game`, `duration`, `log`)\n"
        "• `/status` — Zeigt alle aktiven Server samt IP an\n"
        "• `/log <mode>` — Schaltet Logs um (`all`, `game`, `off`)\n"
        "• `/stop` — Stoppt und löscht den laufenden Server\n"
        "• `/costs` — Zeigt Serverkosten und Spielzeiten an (`timeframe`, `user`)\n"
        "• `/account` — Zeigt dein aktuelles Guthaben / Kontostand\n"
        "• `/cash add` — *(Admin)* Guthabeneinzahlung für einen Nutzer buchen\n"
        "• `/addgameaccount` — Verknüpft deinen Ingame-Namen mit Discord\n"
        "• `/help` — Zeigt diese Übersicht an"
    )

def handle_status() -> str:
    _, resp = rest_api.handle_servers()
    servers = resp.get("data", [])
    if not servers:
        return "⚪ Es läuft aktuell kein Server."
    lines = [
        f"• `{s['name']}` (ID: {s['server_id']}) — `{s.get('status', 'unknown')}` — IP: `{s['ip']}`"
        for s in servers
    ]
    return "🟢 **Aktive Server:**\n" + "\n".join(lines)

def handle_stop() -> str:
    status, resp = rest_api.handle_stop({})
    if status == 400:
        return "⚪ Kein laufender Server zum Stoppen vorhanden."
    if status != 200:
        return f"❌ Fehler beim Stoppen: {resp.get('error')}"

    target = resp["target"]
    if resp.get("mode") == "graceful":
        return f"🛑 **Shutdown für `{target['name']}` eingeleitet.** (Container sichern & VM löschen)"
    return f"🛑 **Server `{target['name']}` direkt via Hetzner-API gelöscht.**"

def handle_start(data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    try:
        status, resp = rest_api.handle_start(options)
        if status != 200:
            return f"❌ Fehler beim Starten des Servers: {resp.get('error')}"

        res = resp["data"]
        log_mode = resp["log_mode"]
        addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
        log_labels = {"none": "⚪ Aus", "game": "🎮 Nur Game", "all": "📡 Alles (Game + System)"}
        return (
            f"🟡 **Hardware wird hochgefahren!**\n"
            f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
            f"🌐 **Adresse:** {addr}\n"
            f"⏳ **Laufzeit:** {res.get('lifetime_readable')}\n"
            f"📋 **Live-Logs:** {log_labels.get(log_mode, log_mode)}\n\n"
            f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
        )
    except Exception as e:
        return f"❌ Fehler beim Starten des Servers: {e}"

def handle_log(data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    mode = str(options.get("mode", "game")).strip().lower()

    status, resp = rest_api.handle_log({"mode": mode})
    if status == 400:
        return "⚪ Kein aktiver Server online."
    if status != 200:
        return f"⚠ {resp.get('error')}"

    cur_mode = resp.get("mode", mode)
    return f"📡 **Live-Logs wurden umgestellt auf: `{cur_mode.upper()}`**"