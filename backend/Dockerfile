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

# Comando por defecto: servidor de producción (gunicorn + settings de prod).
# docker-compose lo sobreescribe en desarrollo con runserver.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
