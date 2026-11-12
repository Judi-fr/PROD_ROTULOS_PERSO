"""Hosts permitidos por rango de red (``ALLOWED_CIDR_NETS``).

Django solo acepta en ``ALLOWED_HOSTS`` nombres exactos, subdominios con
punto inicial o ``"*"``: un patrón como ``"172.31.*"`` no matchea nada. Pero
detrás de un balanceador de AWS los health checks llegan con la IP privada
del contenedor como Host, y esa IP cambia en cada despliegue.

Este middleware resuelve eso sin abrir ``"*"`` de verdad: ``prod.py`` deja
``ALLOWED_HOSTS = ["*"]`` para que Django no corte antes, y la validación
real pasa acá — el Host tiene que estar en la lista original
(``ALLOWED_HOSTS_ORIGINAL``) o ser una IP dentro de ``ALLOWED_CIDR_NETS``.
Cualquier otro termina en 400, igual que con la validación de Django.
Va PRIMERO en ``MIDDLEWARE``: SecurityMiddleware ya lee el Host para
redirigir a HTTPS.
"""

import ipaddress

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http.request import split_domain_port, validate_host


class AllowedCIDRMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # La variable de entorno se escribe a mano: "a, b" deja " b" con el
        # espacio, y ese host nunca matchearía.
        self.allowed_hosts = [h.strip() for h in settings.ALLOWED_HOSTS_ORIGINAL if h.strip()]
        self.networks = [
            ipaddress.ip_network(net, strict=False) for net in settings.ALLOWED_CIDR_NETS
        ]

    def __call__(self, request):
        host = request.get_host()
        if not self._is_allowed(host):
            raise DisallowedHost(f"Host no permitido: {host!r}.")
        return self.get_response(request)

    def _is_allowed(self, host):
        domain, _port = split_domain_port(host)
        if not domain:
            return False
        if validate_host(domain, self.allowed_hosts):
            return True
        try:
            ip = ipaddress.ip_address(domain.strip("[]"))
        except ValueError:
            return False
        return any(ip in net for net in self.networks)
