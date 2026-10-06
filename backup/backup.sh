#!/bin/sh
# Un backup completo: base de datos + archivos subidos (media).
#
#   /backups/AAAA-MM-DD_HHMM/
#     base.dump      pg_dump en formato custom (comprimido, se restaura con pg_restore)
#     media.tar.gz   la carpeta media entera
#     SHA256SUMS     para detectar una copia corrupta antes de restaurarla
#     INFO.txt       fecha, versión de Postgres y tamaños
#
# Se arma en una carpeta ".en-curso-*" y recién al final se renombra: una
# copia a medias (disco lleno, corte de luz) nunca queda con nombre de copia
# válida. Si RESTIC_REPOSITORY está definido, además se sube cifrada afuera.
#
# Conexión a la base: PGHOST/PGUSER/PGPASSWORD/PGDATABASE (docker-compose).
set -eu

DEST=/backups
KEEP="${BACKUP_KEEP_LOCAL:-7}"
ts=$(date +%Y-%m-%d_%H%M)
tmp="$DEST/.en-curso-$ts"
final="$DEST/$ts"

log() { echo "[backup] $(date '+%F %T') $*"; }

mkdir -p "$DEST"
rm -rf "$DEST"/.en-curso-*   # restos de una corrida que murió a mitad de camino
mkdir "$tmp"

log "base de datos -> pg_dump"
pg_dump --format=custom --compress=6 --no-owner --file="$tmp/base.dump"
# Un dump que pg_restore no puede leer no es un backup: se verifica ya.
pg_restore --list "$tmp/base.dump" > /dev/null

log "archivos -> media.tar.gz"
tar -czf "$tmp/media.tar.gz" -C /media .

(cd "$tmp" && sha256sum base.dump media.tar.gz > SHA256SUMS)
{
    echo "fecha:     $(date '+%F %T %Z')"
    echo "postgres:  $(psql -Atc 'show server_version')"
    echo "base:      $(du -h "$tmp/base.dump" | cut -f1)"
    echo "media:     $(du -h "$tmp/media.tar.gz" | cut -f1) ($(find /media -type f | wc -l) archivos)"
} > "$tmp/INFO.txt"

if [ -e "$final" ]; then
    final="$final-$(date +%S)"   # dos corridas en el mismo minuto
fi
mv "$tmp" "$final"
log "copia local lista: $final ($(du -sh "$final" | cut -f1))"

# Rotación local: quedan las KEEP más nuevas. Los nombres empiezan con la
# fecha, así que el orden alfabético es el cronológico.
total=$(find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '20*' | wc -l)
sobran=$((total - KEEP))
if [ "$sobran" -gt 0 ]; then
    find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | head -n "$sobran" | while read -r viejo; do
        log "rotación: borro $viejo"
        rm -rf "$viejo"
    done
fi

# Copia externa (opcional) con restic: cifrada antes de salir del servidor.
if [ -n "${RESTIC_REPOSITORY:-}" ]; then
    if ! restic cat config > /dev/null 2>&1; then
        log "restic: repositorio nuevo, inicializando"
        restic init
    fi
    log "restic: subiendo"
    restic backup --host rotulos --tag rotulos "$final"
    # Cada copia es una carpeta con otro nombre: sin --group-by, restic las
    # trataría como cosas distintas y no borraría ninguna.
    restic forget --host rotulos --tag rotulos --group-by host,tags \
        --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
    restic check
    log "restic: ok"
fi

# Lo lee el chequeo de salud: si pasa más de un día sin actualizarse, el
# contenedor queda "unhealthy" (también si falló solo la copia externa).
date +%s > "$DEST/.ultimo-ok"
log "backup terminado"
