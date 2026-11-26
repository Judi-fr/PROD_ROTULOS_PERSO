"""La IP real del cliente.

``X-Forwarded-For`` lo puede mandar cualquiera: cada proxy AGREGA al final la
IP de quien le habló, así que solo son confiables las últimas
``TRUSTED_PROXIES`` entradas (las que agregaron nuestros proxies). La IP del
cliente es la que agregó el proxy más externo: contando desde la derecha, la
número ``TRUSTED_PROXIES``. Sin proxies (0, desarrollo) el encabezado se
ignora y vale ``REMOTE_ADDR``.

Es la misma regla que DRF aplica a sus límites con ``NUM_PROXIES``
(``base.py`` los iguala), así la auditoría y los límites ven la misma IP.
Antes la auditoría tomaba la PRIMERA entrada (la que inventa el cliente) y
los límites usaban el encabezado entero: cambiándolo en cada intento se
esquivaban los límites por IP y se ensuciaba la auditoría.
"""

import ipaddress

from django.conf import settings


def _valid(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request) -> str | None:
    if request is None:
        return None
    remote = request.META.get("REMOTE_ADDR") or None
    proxies = getattr(settings, "TRUSTED_PROXIES", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    if proxies <= 0 or not forwarded:
        return remote
    entries = [part.strip() for part in forwarded.split(",") if part.strip()]
    if len(entries) < proxies:
        return remote
    return _valid(entries[-proxies]) or remote
