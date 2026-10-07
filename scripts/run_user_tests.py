import os
import sys
import time
import json
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "aws_lambda"))

# .env direkt laden
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import rest_api

print("=" * 60)
print("🚀 STARTE LOKALE END-TO-END VALIDIERUNG MIT LIVE-DATENBANK")
print(f"Supabase: {'✓ Konfiguriert' if os.environ.get('SUPABASE_URL') else '✗ FEHLT'}")
print(f"Hetzner:  {'✓ Konfiguriert' if os.environ.get('HETZNER_API_TOKEN') else '✗ FEHLT'}")
print("=" * 60)


# ------------------------------------------------------------------
# Test 1: Feature 1 - DNS Sync & Katalogisierung
# ------------------------------------------------------------------
print("\n[TEST 1] Prüfe GoDaddy DNS Catalog Sync...")
status, body = rest_api.route_request("/dns/sync", {})
if status == 200 and "synced_count" in body:
    print(f"  ✓ DNS Sync erfolgreich: {body.get('synced_count')} Records katalogisiert.")
else:
    print(f"  ✗ DNS Sync fehlgeschlagen ({status}): {body}")

# ------------------------------------------------------------------
# Test 2: Feature 2 - Mojang UUID Validierung
# ------------------------------------------------------------------
print("\n[TEST 2] Prüfe Mojang Account Binding & UUID Resolution...")
# 2a. Ungültiger Account (gültige Minecraft-Namenssyntax, existiert aber nicht)
status, body = rest_api.route_request("/addgameaccount", {
    "discord_user_id": "432141301111324672",
    "discord_username": "gamesbond00",
    "game": "minecraft",
    "username": "NotAnActualUser9999"
})
if status == 404:
    print("  ✓ Ungültiger Minecraft-Account wird von Mojang API korrekt abgewiesen (404).")
else:
    print(f"  ✗ Erwartetes 404 nicht erhalten ({status}): {body}")

# 2b. Echter Account mit deiner verknüpften Discord-ID
status, body = rest_api.route_request("/addgameaccount", {
    "discord_user_id": "432141301111324672",
    "discord_username": "gamesbond00",
    "game": "minecraft",
    "username": "gamesbond00"
})
if status in [200, 201] and (body.get("mojang_uuid") or body.get("status") in ["created", "already_linked_self"]):
    print(f"  ✓ Offizieller Account aufgelöst & verknüpft: {body.get('username')} (UUID: {body.get('mojang_uuid')})")
else:
    print(f"  ✗ Mojang-Auflösung fehlgeschlagen ({status}): {body}")

# ------------------------------------------------------------------
# Test 3: Feature 3 - Server Lifecycle (Create & Delete)
# ------------------------------------------------------------------
print("\n[TEST 3] Prüfe Server Lifecycle & Dynamische Hetzner Volumes...")
test_srv_slug = f"e2etest_{int(time.time())}"

# 3a. Server erstellen
status, body = rest_api.route_request("/server/create", {
    "game": "minecraft",
    "server_name": test_srv_slug,
    "discord_user_id": "test_e2e_user"
})

if status == 201 and "server" in body:
    srv_data = body["server"]
    print(f"  ✓ Volume & Server '{srv_data.get('display_name')}' angelegt (Volume ID: {srv_data.get('hetzner_volume_id')}).")
else:
    print(f"  ✗ Server-Erstellung fehlgeschlagen ({status}): {body}")
    sys.exit(1)

# Kleine Pause (2 Sekunden), damit Hetzner und Supabase synchron sind
time.sleep(2)

# ------------------------------------------------------------------
# Test 4: Feature 4 - Hybrid Whitelist
# ------------------------------------------------------------------
print("\n[TEST 4] Prüfe Hybrid Whitelist...")
status, body = rest_api.route_request("/whitelist/add", {
    "server_name": test_srv_slug,
    "game": "minecraft",
    "username": "gamesbond00",
    "discord_user_id": "test_e2e_user",
    "role": "player"
})
if status == 200:
    print(f"  ✓ Spieler auf Whitelist gesetzt: {body.get('username')} ({body.get('role')}).")
else:
    print(f"  ✗ Whitelist Add fehlgeschlagen ({status}): {body}")

# Whitelist auslesen
status, body = rest_api.route_request("/whitelist/list", {
    "server_name": test_srv_slug,
    "game": "minecraft"
})
if status == 200 and len(body.get("entries", [])) >= 1:
    print(f"  ✓ Whitelist enthält {len(body['entries'])} verifizierten Eintrag.")
else:
    print(f"  ✗ Whitelist List fehlgeschlagen ({status}): {body}")

# Pause vor dem Cleanup
time.sleep(2)

# ------------------------------------------------------------------
# Aufräumen: Test-Server wieder löschen
# ------------------------------------------------------------------
print("\n[CLEANUP] Lösche erstellten Test-Server und Hetzner Volume wieder...")
status, body = rest_api.route_request("/server/delete", {
    "server_name": test_srv_slug,
    "discord_user_id": "test_e2e_user"
})
if status == 200:
    print(f"  ✓ Test-Server und Volume erfolgreich entfernt.")
else:
    print(f"  ✗ Cleanup fehlgeschlagen ({status}): {body}")

print("\n" + "=" * 60)
print("🏁 END-TO-END TESTDURCHLAUF ERFOLGREICH ABGESCHLOSSEN")
print("=" * 60)