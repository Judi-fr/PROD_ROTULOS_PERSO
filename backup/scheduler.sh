#!/bin/sh
# Corre backup.sh una vez por día a la hora BACKUP_HOUR (hora local, TZ).
#
# Un bucle con sleep y no cron: el cron de busybox no les pasa las variables
# de entorno a los trabajos, y acá todo (credenciales de la base y de restic)
# llega por entorno.
set -u

HORA="${BACKUP_HOUR:-03:00}"

log() { echo "[backup] $(date '+%F %T') $*"; }

# docker stop manda SIGTERM: sin esto el shell (PID 1) lo ignora y Docker
# lo mata a los 10 segundos.
trap 'log "detenido"; exit 0' TERM INT

# Un backup al arrancar: cada despliegue nuevo queda con una copia hecha y
# el chequeo de salud tiene un dato desde el primer minuto.
if [ "${BACKUP_RUN_ON_START:-1}" = "1" ]; then
    backup.sh || log "ERROR: el backup falló (ver arriba)"
fi

while true; do
    ahora=$(date +%s)
    objetivo=$(date -d "$(date +%F) $HORA" +%s)
    if [ "$objetivo" -le "$ahora" ]; then
        objetivo=$((objetivo + 86400))
    fi
    log "próximo backup: $(date -d "@$objetivo" '+%F %H:%M')"
    sleep $((objetivo - ahora)) &
    wait $!
    backup.sh || log "ERROR: el backup falló (ver arriba)"
done
