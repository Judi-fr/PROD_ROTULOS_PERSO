# Imagen de backups: la misma de Postgres que la base (así pg_dump y
# pg_restore son de la MISMA versión mayor que el servidor) más restic, que
# cifra y sube la copia a un almacenamiento externo.
FROM docker.io/library/postgres:17-alpine

RUN apk add --no-cache restic tzdata

COPY scheduler.sh backup.sh restore.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/scheduler.sh /usr/local/bin/backup.sh /usr/local/bin/restore.sh

# La imagen de Postgres arranca un servidor de base por defecto: acá no.
ENTRYPOINT []
CMD ["scheduler.sh"]
