#!/bin/sh
# Prepara un servidor Ubuntu 24.04 (Lightsail, o cualquier VPS) para correr
# docker-compose.prod.yml.
#
# Se pega como "launch script" al crear la instancia (corre una vez, como root,
# en el primer arranque) o se corre a mano con sudo. No despliega la app: deja
# Docker + Compose v2, swap y la carpeta /opt/rotulos lista para clonar.
# El resto (clonar, .env, up) sigue HELP_ME.md > "En AWS (Lightsail)".
set -eu

export DEBIAN_FRONTEND=noninteractive

# Docker desde el repositorio oficial: el paquete docker.io de Ubuntu no trae
# el plugin de Compose v2, y docker-compose 1.x no entiende estos archivos.
apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# El usuario por defecto de Ubuntu (ubuntu) usa docker sin sudo.
usermod -aG docker ubuntu

# Swap de 2 GB: construir las imágenes (pip de reportlab, Pillow, etc.) con
# 2 GB de RAM y Postgres + gunicorn corriendo puede quedarse sin memoria, y el
# kernel mata un proceso al azar en vez de fallar prolijo.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

install -d -o ubuntu -g ubuntu /opt/rotulos
