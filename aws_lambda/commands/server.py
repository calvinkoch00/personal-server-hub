import os
import rest_api

def get_help_message() -> str:
    return (
        "📖 **Server Hub – Anleitung & Befehle**\n\n"
        "**1️⃣ Einem bestehenden Server beitreten (Schritt-für-Schritt):**\n"
        "1. Account einmalig registrieren: `/addgameaccount game: minecraft username: <DeinIngameName>`\n"
        "2. Whitelist prüfen/hinzufügen: `/whitelist add username: <DeinIngameName> server: <ServerName>`\n"
        "3. Server starten: `/server start name: <ServerName> duration: 2h`\n"
        "4. In Minecraft direkt verbinden mit der Domain aus der Startmeldung (z. B. `<subdomain>.calvinkoch.ch`).\n\n"
        "**2️⃣ Einen neuen Server erstellen & beitreten:**\n"
        "1. Account verknüpfen: `/addgameaccount game: minecraft username: <DeinIngameName>`\n"
        "2. Server anlegen: `/server create name: <Name> subdomain: <WunschDomain>`\n"
        "   *(Deine verknüpften Accounts werden automatisch als Admin gewitelistet!)*\n"
        "3. Freunde hinzufügen: `/whitelist add username: <Freund> server: <Name>`\n"
        "4. Server starten & losspielen: `/server start name: <Name> duration: 4h`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 **Verfügbare Befehle:**\n"
        "• `/server start [name] [duration] [log]` — Startet einen Server\n"
        "• `/server stop [name]` — Stoppt einen laufenden Server und setzt DNS zurück\n"
        "• `/server reload-files <server>` — Aktualisiert Agenten-Dateien ohne Downtime\n"
        "• `/server status` — Zeigt alle registrierten Server und deren Status\n"
        "• `/server create <name> [game] [subdomain]` — Erstellt ein neues Server-Volume\n"
        "• `/server delete <server>` — Löscht einen Server nach 2-Stufen-Bestätigung\n"
        "• `/whitelist add <username> <server> [role]` — Spieler hinzufügen / Rolle anpassen\n"
        "• `/whitelist remove <username> <server>` — Spieler von Whitelist entfernen\n"
        "• `/whitelist list <server>` — Zeigt gewhitelistete Spieler eines Servers\n"
        "• `/status` — Zeigt laufende Instanzen samt Live-IP\n"
        "• `/log <mode> [server]` — Live-Logs umschalten (`game`, `all`, `off`)\n"
        "• `/costs [timeframe] [user]` — Kosten und Spielzeiten einsehen\n"
        "• `/account [user]` — Guthaben und Saldo anzeigen\n"
        "• `/cash add <user> <amount> [currency] [note]` — Guthaben buchen (Admin)\n"
        "• `/addgameaccount <game> <username>` — Ingame-Account mit Discord koppeln\n"
        "• `/help` — Zeigt diese Anleitung an"
    )

def handle_status() -> str:
    _, resp = rest_api.handle_servers()
    servers = resp.get("servers", resp.get("data", []))
    if not servers:
        return "⚪ Keine registrierten Server vorhanden."

    lines = []
    for s in servers:
        status = s.get("status", "offline")
        icon = "🟢" if status == "online" else "⚪"
        sub = s.get("subdomain") or s.get("server_name")
        dns_text = f" | `{sub}.calvinkoch.ch`" if sub else ""
        lines.append(f"{icon} `{s.get('display_name', s.get('name'))}` — Status: `{status}`{dns_text}")

    return "🖥️ **Server-Übersicht:**\n" + "\n".join(lines)

def handle_stop(payload: dict | None = None) -> str:
    status, resp = rest_api.handle_stop(payload or {})
    if status == 400:
        return "⚪ Kein laufender Server zum Stoppen vorhanden."
    if status == 404:
        return f"⚪ {resp.get('error')}"
    if status != 200:
        return f"❌ Fehler beim Stoppen: {resp.get('error')}"

    target = resp.get("target", {})
    if resp.get("mode") == "graceful":
        return f"🛑 **Shutdown für `{target.get('name')}` eingeleitet.** (Container sichern & VM löschen)"
    return f"🛑 **Server `{target.get('name')}` direkt via Hetzner-API gelöscht.**"

def handle_start(data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    if "name" in options and "server_name" not in options:
        options["server_name"] = options.pop("name")

    try:
        status, resp = rest_api.handle_start(options)
        if status != 200:
            return f"❌ Fehler beim Starten des Servers: {resp.get('error')}"

        res = resp["data"]
        log_mode = resp.get("log_mode", "none")
        addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
        log_labels = {"none": "⚪ Aus", "game": "🎮 Nur Game", "all": "📡 Alles (Game + System)"}
        return (
            f"🟡 **Hardware wird hochgefahren!**\n"
            f"🎮 **Server:** `{res.get('name')}`\n"
            f"🌐 **Adresse:** {addr}\n"
            f"⏳ **Laufzeit:** {res.get('lifetime_readable')}\n"
            f"📋 **Live-Logs:** {log_labels.get(log_mode, log_mode)}\n\n"
            f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
        )
    except Exception as e:
        return f"❌ Fehler beim Starten des Servers: {e}"

def handle_create(data: dict, caller_id: str) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    payload = {
        "server_name": options.get("name"),
        "game": options.get("game", "minecraft"),
        "custom_subdomain": options.get("subdomain"),
        "discord_user_id": caller_id
    }
    status, resp = rest_api.handle_server_create(payload)
    if status == 201:
        srv = resp.get("server", {})
        slug = srv.get("server_slug") or resp.get("server_slug") or options.get("name")
        sub = srv.get("subdomain") or resp.get("subdomain") or slug
        return (
            f"✅ **Server `{srv.get('display_name', f'minecraft-{slug}')}` erfolgreich erstellt!**\n"
            f"• Hetzner Volume: `{srv.get('hetzner_volume_id')}` (20 GB)\n"
            f"• Adresse: `{sub}.calvinkoch.ch`\n"
            f"• Status: `offline` (kann jetzt per `/server start name: {slug}` gestartet werden)"
        )
    return f"❌ {resp.get('error')}"

def handle_delete(sub_options: dict, caller_id: str) -> dict:
    server_slug = str(sub_options.get("server") or sub_options.get("name") or "").strip()
    if not server_slug:
        return {"content": "❌ Bitte gib einen Servernamen an: `/server delete server: <name>`"}

    return {
        "content": (
            f"⚠️ **Achtung:** Möchtest du den Server `{server_slug}` und sein gesamtes Volume "
            f"wirklich **unwiderruflich löschen**?\nAlle Weltdaten gehen dabei verloren!"
        ),
        "components": [
          {
            "type": 1,
            "components": [
              {
                "type": 2,
                "style": 4,  # Danger (Rot)
                "label": "Ja, endgültig löschen",
                "custom_id": f"confirm_del:{server_slug}:{caller_id}"
              },
              {
                "type": 2,
                "style": 2,  # Secondary (Grau)
                "label": "Abbrechen",
                "custom_id": f"cancel_del:{caller_id}"
              }
            ]
          }
        ]
    }

def handle_log(data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    mode = str(options.get("mode", "game")).strip().lower()
    server_param = str(options.get("server") or options.get("name") or "default").strip()

    status, resp = rest_api.handle_log({"mode": mode, "server_name": server_param})
    if status != 200:
        return f"⚠ {resp.get('error')}"

    cur_mode = resp.get("mode", mode).upper()
    srv_name = resp.get("server", server_param)
    sync_txt = " (Live auf Server umgestellt!)" if resp.get("live_synced") else " (gespeichert für nächsten Serverstart)"
    
    return f"📡 **Live-Logs für `{srv_name}` wurden umgestellt auf: `{cur_mode}`**{sync_txt}"

def handle_reload_files(sub_options: dict) -> str:
    server_param = sub_options.get("server") or sub_options.get("name")
    if not server_param:
        return "❌ Bitte gib einen Servernamen an."

    status, resp = rest_api.handle_server_reload_files({"server_name": server_param})
    if status == 200:
        return f"🔄 **Zero-Downtime Reload:** {resp.get('message')}"
    return f"❌ {resp.get('error')}"