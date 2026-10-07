#!/bin/sh
# Restaura un backup: REEMPLAZA la base y la carpeta media por las de la copia.
#
# Uso (desde la carpeta del docker-compose.prod.yml, ver HELP_ME.md):
#   docker compose -f docker-compose.prod.yml stop api worker
#   docker compose -f docker-compose.prod.yml run --rm restore              # muestra qué haría
#   docker compose -f docker-compose.prod.yml run --rm restore latest --yes
#   docker compose -f docker-compose.prod.yml start api worker
#
# Argumentos:
#   latest | AAAA-MM-DD_HHMM   copia local de /backups (por defecto: latest)
#   --restic                   bajarla de la copia externa (restic) en vez de /backups;
#                              con --restic el primer argumento es el snapshot (o latest)
#   --yes                      hacerlo de verdad (sin esto, solo muestra el plan)
set -eu

ORIGEN="latest"
DESDE_RESTIC=0
CONFIRMADO=0
for arg in "$@"; do
    case "$arg" in
        --restic) DESDE_RESTIC=1 ;;
        --yes) CONFIRMADO=1 ;;
        -*) echo "Opción desconocida: $arg" >&2; exit 2 ;;
        *) ORIGEN="$arg" ;;
    esac
done

log() { echo "[restore] $*"; }
fallar() { echo "[restore] ERROR: $*" >&2; exit 1; }

# --- 1. Ubicar la copia -------------------------------------------------------
if [ "$DESDE_RESTIC" = "1" ]; then
    [ -n "${RESTIC_REPOSITORY:-}" ] || fallar "RESTIC_REPOSITORY no está definido."
    destino=/tmp/restic-restore
    rm -rf "$destino"
    log "bajando el snapshot '$ORIGEN' de restic"
    restic restore "$ORIGEN" --host rotulos --tag rotulos --target "$destino"
    DIR=$(dirname "$(find "$destino" -name base.dump | head -n 1)")
elif [ "$ORIGEN" = "latest" ]; then
    DIR=$(find /backups -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | tail -n 1)
else
    DIR="/backups/$ORIGEN"
fi

[ -n "$DIR" ] && [ -f "$DIR/base.dump" ] && [ -f "$DIR/media.tar.gz" ] \
    || fallar "no encontré una copia completa (buscaba '$ORIGEN'). Copias locales: $(find /backups -mindepth 1 -maxdepth 1 -type d -name '20*' -exec basename {} \; 2>/dev/null | sort | tr '\n' ' ')"

# --- 2. Verificar que la copia está sana --------------------------------------
(cd "$DIR" && sha256sum -c -s SHA256SUMS) || fallar "la copia $DIR está corrupta (no coinciden las sumas SHA256)."
pg_restore --list "$DIR/base.dump" > /dev/null || fallar "pg_restore no puede leer $DIR/base.dump."

log "copia a restaurar: $DIR"
sed 's/^/          /' "$DIR/INFO.txt" 2>/dev/null || true

# --- 3. Nadie más usando la base ----------------------------------------------
# Restaurar con la API conectada deja sesiones viendo tablas que se borran y
# se recrean debajo de ellas. Este contenedor no tiene acceso a Docker (a
# propósito), así que no puede frenarlas: avisa y se detiene.
# Es una red, no una garantía: la API abre conexión solo mientras atiende un
# pedido, así que encendida y ociosa puede no aparecer. Por eso el paso de
# frenar api y worker está en las instrucciones, y la base se restaura en una
# sola transacción (un pedido que llegue en el medio espera y no ve nada a medias).
otros=$(psql -Atc "select count(*) from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid() and backend_type = 'client backend'")
if [ "$otros" -gt 0 ]; then
    fallar "hay $otros conexión(es) abiertas a la base. Frená la API y el worker primero:
    docker compose -f docker-compose.prod.yml stop api worker"
fi

if [ "$CONFIRMADO" != "1" ]; then
    log "PLAN (no se cambió nada):"
    log "  - la base '$PGDATABASE' se reemplaza por la de la copia"
    log "  - la carpeta media se vacía y se reemplaza por la de la copia"
    log "Para hacerlo de verdad, repetí el comando agregando --yes"
    exit 0
fi

# --- 4. Restaurar -------------------------------------------------------------
log "restaurando la base (en una sola transacción: si falla, no queda a medias)"
pg_restore --clean --if-exists --no-owner --single-transaction --dbname="$PGDATABASE" "$DIR/base.dump"

log "restaurando media"
find /media -mindepth 1 -delete
tar -xzf "$DIR/media.tar.gz" -C /media

log "listo. Volvé a arrancar la API y el worker:
    docker compose -f docker-compose.prod.yml start api worker"
