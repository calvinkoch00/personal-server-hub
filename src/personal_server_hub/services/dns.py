"""Deprecated redirect: the implementation lives in personal_server_hub.application.dns.

Delete this module once all callers import from application.dns directly.
"""
from personal_server_hub.application import dns as _impl


def environment_subdomain(subdomain: str) -> str:
    return _impl.environment_subdomain(subdomain)


def fallback_server_subdomain(game: str, server_slug: str) -> str:
    return _impl.fallback_server_subdomain(game, server_slug)


def update_godaddy_dns(ip: str, subdomain: str, server_id: str | None = None) -> bool:
    return _impl.update_godaddy_dns(ip, subdomain=subdomain, server_id=server_id)


def delete_godaddy_dns(subdomain: str) -> bool:
    return _impl.delete_godaddy_dns(subdomain)


def find_subdomains_by_ip(target_ip: str) -> list[str]:
    return _impl.find_subdomains_by_ip(target_ip)


def sync_all_dns_from_godaddy() -> dict:
    return _impl.sync_all_dns_from_godaddy()
