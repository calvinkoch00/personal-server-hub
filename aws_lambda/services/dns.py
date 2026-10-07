import os
import json
import urllib.request
from datetime import datetime, timezone
from services.supabase import supabase_client_request

GODADDY_API_KEY = os.environ.get("GODADDY_API_KEY")
GODADDY_API_SECRET = os.environ.get("GODADDY_API_SECRET")
GODADDY_DOMAIN = os.environ.get("GODADDY_DOMAIN", "calvinkoch.ch")
GODADDY_SUBDOMAIN = os.environ.get("GODADDY_SUBDOMAIN", "mc")

def _get_headers() -> dict:
    return {
        "Authorization": f"sso-key {GODADDY_API_KEY}:{GODADDY_API_SECRET}",
        "Content-Type": "application/json"
    }

def update_godaddy_dns(ip: str, subdomain: str | None = None, server_id: str | None = None) -> bool:
    """
    Aktualisiert den A-Record bei GoDaddy und spiegelt ihn in dim_dns_records.
    Voll abwärtskompatibel mit update_godaddy_dns(ip).
    """
    if not GODADDY_API_KEY or not GODADDY_API_SECRET:
        print("[DNS WARNING] GoDaddy API Keys fehlen!")
        return False

    sub = (subdomain or GODADDY_SUBDOMAIN).strip().lower()
    url = f"https://api.godaddy.com/v1/domains/{GODADDY_DOMAIN}/records/A/{sub}"
    payload = [{"data": ip, "ttl": 600}]
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_get_headers(),
        method="PUT"
    )

    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            print(f"[DNS] GoDaddy Record {sub}.{GODADDY_DOMAIN} -> {ip} aktualisiert ({resp.status})")
    except Exception as e:
        print(f"[DNS] GoDaddy DNS Fehler: {e}")
        return False

    # Snapshot in Supabase spiegeln (Fail-safe, wirft keine Exceptions)
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase_client_request(
            "dim_dns_records",
            method="POST",
            data={
                "domain": GODADDY_DOMAIN,
                "subdomain": sub,
                "record_type": "A",
                "record_value": ip,
                "ttl": 600,
                "used_for": "game-server",
                "server_id": server_id,
                "last_synced_with_godaddy": now_iso
            },
            headers_extra={"Prefer": "resolution=merge-duplicates"}
        )
    except Exception as e:
        print(f"[DNS WARNING] Supabase Snapshot fehlgeschlagen: {e}")

    return True

def delete_godaddy_dns(subdomain: str) -> bool:
    """Löscht einen A-Record bei GoDaddy und entfernt ihn aus dim_dns_records."""
    if not GODADDY_API_KEY or not GODADDY_API_SECRET:
        return False

    sub = subdomain.strip().lower()
    url = f"https://api.godaddy.com/v1/domains/{GODADDY_DOMAIN}/records/A/{sub}"
    req = urllib.request.Request(url, headers=_get_headers(), method="DELETE")

    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            print(f"[DNS] GoDaddy Record {sub}.{GODADDY_DOMAIN} gelöscht ({resp.status})")
    except Exception as e:
        print(f"[DNS] Fehler beim Löschen bei GoDaddy: {e}")
        return False

    supabase_client_request(
        f"dim_dns_records?domain=eq.{GODADDY_DOMAIN}&subdomain=eq.{sub}&record_type=eq.A",
        method="DELETE"
    )
    return True

def sync_all_dns_from_godaddy() -> dict:
    """Holt alle Records von GoDaddy und speichert sie gespiegelt in dim_dns_records."""
    if not GODADDY_API_KEY or not GODADDY_API_SECRET:
        return {"error": "GoDaddy API Keys fehlen"}

    url = f"https://api.godaddy.com/v1/domains/{GODADDY_DOMAIN}/records"
    req = urllib.request.Request(url, headers=_get_headers(), method="GET")

    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            remote_records = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"GoDaddy Abruf fehlgeschlagen: {e}"}

    now_iso = datetime.now(timezone.utc).isoformat()
    synced = []

    for rec in remote_records:
        r_type = rec.get("type", "").upper()
        if r_type not in ["A", "AAAA", "CNAME", "TXT", "MX"]:
            continue

        sub = rec.get("name", "").lower()
        used_for = "game-server" if sub in ["mc", "minecraft"] or "server" in sub else "other"
        if sub in ["@", "www"]:
            used_for = "website"

        supabase_client_request(
            "dim_dns_records",
            method="POST",
            data={
                "domain": GODADDY_DOMAIN,
                "subdomain": sub,
                "record_type": r_type,
                "record_value": rec.get("data", ""),
                "ttl": int(rec.get("ttl", 600)),
                "used_for": used_for,
                "last_synced_with_godaddy": now_iso
            },
            headers_extra={"Prefer": "resolution=merge-duplicates"}
        )
        synced.append(f"{sub} ({r_type})")

    return {
        "domain": GODADDY_DOMAIN,
        "synced_count": len(synced),
        "records": synced
    }