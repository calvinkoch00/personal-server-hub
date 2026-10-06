import os
import json
import urllib.request

GODADDY_API_KEY = os.environ.get("GODADDY_API_KEY")
GODADDY_API_SECRET = os.environ.get("GODADDY_API_SECRET")
GODADDY_DOMAIN = os.environ.get("GODADDY_DOMAIN", "calvinkoch.ch")
GODADDY_SUBDOMAIN = os.environ.get("GODADDY_SUBDOMAIN", "mc")


def update_godaddy_dns(ip: str):
    """Aktualisiert den A-Record bei GoDaddy auf die neue Server-IP."""
    if not GODADDY_API_KEY or not GODADDY_API_SECRET:
        return

    url = f"https://api.godaddy.com/v1/domains/{GODADDY_DOMAIN}/records/A/{GODADDY_SUBDOMAIN}"
    headers = {
        "Authorization": f"sso-key {GODADDY_API_KEY}:{GODADDY_API_SECRET}",
        "Content-Type": "application/json"
    }
    payload = [{"data": ip, "ttl": 600}]
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            print(f"[DNS] GoDaddy Record {GODADDY_SUBDOMAIN}.{GODADDY_DOMAIN} -> {ip} aktualisiert ({resp.status})")
    except Exception as e:
        print(f"[DNS] GoDaddy DNS Fehler: {e}")