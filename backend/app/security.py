"""Schutz vor SSRF: nur http(s)-URLs auf oeffentliche Adressen (ausser explizit erlaubt)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UrlNotAllowed(ValueError):
    pass


def _is_public(ip: ipaddress._BaseAddress) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url(url: str, allow_private: bool = False) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlNotAllowed("Nur http(s)-URLs sind erlaubt.")
    if allow_private:
        return url
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"Host konnte nicht aufgeloest werden: {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not _is_public(ip):
            raise UrlNotAllowed("URLs auf interne/private Adressen sind nicht erlaubt.")
    return url
