import json
import urllib.request
import urllib.error

def format_uuid(uuid_str: str) -> str:
    """Wandelt eine 32-Zeichen unhyphenated UUID in das Format 8-4-4-4-12 um."""
    clean = uuid_str.replace("-", "").strip()
    if len(clean) != 32:
        return uuid_str
    return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"

def get_mojang_profile(username: str) -> tuple[str | None, str | None]:
    """
    Fragt das offizielle Mojang-Profil ab.
    Gibt (formatted_uuid, exact_cased_username) zurück.
    Gibt (None, None) zurück, wenn der Spieler nicht existiert oder Mojang nicht erreichbar ist.
    """
    clean_name = username.strip()
    url = f"https://api.mojang.com/users/profiles/minecraft/{clean_name}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "GameServer-Hub/1.0"}
    )

    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                raw_id = data.get("id")
                official_name = data.get("name", clean_name)
                if raw_id:
                    return format_uuid(raw_id), official_name
    except urllib.error.HTTPError as e:
        if e.code == 404 or e.code == 204:
            # Spieler existiert nicht
            return None, None
        print(f"[MOJANG API WARNING] HTTP {e.code}: {e.reason}", flush=True)
    except Exception as e:
        print(f"[MOJANG API WARNING] Abruf fehlgeschlagen: {e}", flush=True)

    return None, None