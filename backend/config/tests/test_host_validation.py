"""Validación del Host por rango de red (``config/host_validation.py``).

Lo que se fija: una IP privada dentro de ``ALLOWED_CIDR_NETS`` pasa (el
health check del balanceador), los dominios de ``ALLOWED_HOSTS`` siguen
pasando, y todo lo demás sigue cortándose — abrir el rango no puede abrir
cualquier Host.
"""

from django.core.exceptions import DisallowedHost
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from config.host_validation import AllowedCIDRMiddleware


@override_settings(
    ALLOWED_HOSTS=["*"],
    ALLOWED_HOSTS_ORIGINAL=["rotulos.example.com", ".tienda.example.com"],
    ALLOWED_CIDR_NETS=["172.31.0.0/16"],
)
class AllowedCIDRMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.middleware = AllowedCIDRMiddleware(lambda request: HttpResponse("ok"))

    def _call(self, host):
        request = RequestFactory().get("/api/v1/health/", HTTP_HOST=host)
        return self.middleware(request)

    def test_acepta_ip_privada_dentro_del_rango(self):
        self.assertEqual(self._call("172.31.45.12").status_code, 200)

    def test_acepta_ip_del_rango_con_puerto(self):
        self.assertEqual(self._call("172.31.0.7:8000").status_code, 200)

    def test_acepta_dominio_de_allowed_hosts(self):
        self.assertEqual(self._call("rotulos.example.com").status_code, 200)

    def test_acepta_subdominio_con_punto_inicial(self):
        self.assertEqual(self._call("a.tienda.example.com").status_code, 200)

    def test_rechaza_ip_fuera_del_rango(self):
        with self.assertRaises(DisallowedHost):
            self._call("172.32.0.1")

    def test_rechaza_dominio_desconocido(self):
        with self.assertRaises(DisallowedHost):
            self._call("evil.example.net")

    def test_rechaza_ip_publica(self):
        with self.assertRaises(DisallowedHost):
            self._call("3.135.46.69")

    @override_settings(ALLOWED_HOSTS_ORIGINAL=["rotulos.example.com", " 3.140.15.131 ", ""])
    def test_ignora_espacios_alrededor_de_cada_host(self):
        # La variable de entorno se escribe a mano ("a, b"): django-environ
        # separa por coma sin recortar, y " 3.140.15.131" nunca matcheaba.
        middleware = AllowedCIDRMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().get("/", HTTP_HOST="3.140.15.131")
        self.assertEqual(middleware(request).status_code, 200)

    @override_settings(ALLOWED_CIDR_NETS=[])
    def test_sin_rangos_solo_valen_los_hosts(self):
        middleware = AllowedCIDRMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().get("/", HTTP_HOST="172.31.45.12")
        with self.assertRaises(DisallowedHost):
            middleware(request)


class HealthCheckBehindLoadBalancerTests(SimpleTestCase):
    """Lo que hace el balanceador de AWS: GET por HTTP plano, Host = IP
    privada del contenedor, sin X-Forwarded-Proto. Tiene que recibir 200,
    no 400 (Host) ni 301 (redirección a HTTPS) — cualquiera de los dos
    hace que ECS mate la tarea en loop."""

    @override_settings(
        ALLOWED_HOSTS=["*"],
        ALLOWED_HOSTS_ORIGINAL=["rotulos.example.com"],
        ALLOWED_CIDR_NETS=["172.31.0.0/16"],
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^api/v1/health(/|$)"],
    )
    def test_health_check_del_balanceador_recibe_200(self):
        from django.conf import settings

        middleware = ["config.host_validation.AllowedCIDRMiddleware", *settings.MIDDLEWARE]
        with self.settings(MIDDLEWARE=middleware):
            for ruta in ("/api/v1/health/", "/api/v1/health"):
                with self.subTest(ruta=ruta):
                    respuesta = self.client.get(ruta, HTTP_HOST="172.31.19.11:8000")
                    self.assertEqual(respuesta.status_code, 200)
            # El resto de la API sigue redirigiendo a HTTPS.
            otra = self.client.get("/api/v1/auth/me/", HTTP_HOST="rotulos.example.com")
            self.assertEqual(otra.status_code, 301)
