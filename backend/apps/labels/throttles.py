"""Límites propios de los endpoints que dibujan rótulos.

Generar un PDF o un PNG ocupa un worker de gunicorn entero mientras dura (un
lote de 200 rótulos, varios segundos), y en producción hay solo 3. El límite
general de 1000/min por usuario está pensado para navegar, no para esto: un
solo usuario podía dejar la app lenta para todos pidiendo renders en loop.
Las tasas viven en settings (DEFAULT_THROTTLE_RATES) y se ajustan por .env.
"""

from rest_framework.settings import api_settings
from rest_framework.throttling import UserRateThrottle


class LabelBatchThrottle(UserRateThrottle):
    """Lotes de rótulos (``POST /labels/batch/``), por usuario."""

    scope = "labels_batch"


class LabelRenderThrottle(UserRateThrottle):
    """Vistas previas y renders sueltos (PDF/PNG/ZPL), por usuario."""

    scope = "labels_render"


# Los límites generales siguen valiendo; estos se suman.
BATCH_THROTTLES = [*api_settings.DEFAULT_THROTTLE_CLASSES, LabelBatchThrottle]
RENDER_THROTTLES = [*api_settings.DEFAULT_THROTTLE_CLASSES, LabelRenderThrottle]
