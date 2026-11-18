# Imagen de la API de ROTULOS_PERSO
FROM python:3.13-slim

# No generar .pyc y volcar la salida sin buffer (logs en tiempo real)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Fuentes TTF para la vista previa PNG de los diseños (element_layout_render/
# fonts.py busca DejaVu en /usr/share/fonts). La imagen slim no trae ninguna:
# sin esto el render PNG falla con FontNotAvailable. El PDF no las necesita.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias primero para aprovechar la caché de capas:
# si solo cambia el código, no se reinstala nada
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sin privilegios: el contenedor no corre como root.
# staticfiles/ y media/ se crean ACÁ, antes del chown: docker-compose.prod.yml
# monta volúmenes en esas rutas, y un volumen nuevo hereda el dueño de la
# carpeta de la imagen. Si la carpeta no existe, Docker la crea como root y
# appuser no puede escribir: collectstatic falla y la API no arranca (y los
# PDFs de los lotes y los logos de las tiendas no se podrían guardar).
RUN mkdir -p /app/staticfiles /app/media \
    && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Settings de producción por defecto. manage.py arranca en dev si la variable
# no está, y ahí la caché vive en memoria: createcachetable no crearía nada.
# Los dos docker-compose definen su propio DJANGO_SETTINGS_MODULE, así que
# esto solo pesa donde nadie lo define (la task definition de ECS).
ENV DJANGO_SETTINGS_MODULE=config.settings.prod

# Comando por defecto: migrar, crear la tabla de caché y servir con gunicorn.
# Lo usa ECS, que corre la imagen tal cual: sin esto, cada despliegue con
# migraciones nuevas dejaba la API rota hasta correrlas a mano. Los
# docker-compose lo sobreescriben (runserver en dev; en prod su propio
# comando, que ya migra). Con más de una réplica las migraciones correrían
# en paralelo: ahí pasan a ser un paso aparte del despliegue.
# `exec` deja a gunicorn como PID 1, para que reciba el SIGTERM de ECS.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 150"]
