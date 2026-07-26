#!/bin/sh
# Arranque del contenedor: deja la base al día y levanta el servidor.
set -e

# Si le pasan un comando, corre eso y nada más. Es lo que permite entrar a hacer
# una tarea puntual sin que además arranque el servidor:
#   docker compose run --rm web python scripts/inicializar_db.py --demo
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Idempotente y rápido: crea las tablas que falten, agrega las columnas nuevas y
# recarga las Cartas de Exploración. Sobre un volumen vacío, esto es lo que arma
# la base la primera vez; sobre uno que ya tiene datos, no toca nada de eso.
# Con INICIALIZAR_DB=0 se saltea, por si alguna vez hay que arrancar sin tocarla.
if [ "${INICIALIZAR_DB:-1}" = "1" ]; then
    python scripts/inicializar_db.py
fi

# Un solo worker, a propósito: la base es SQLite y un solo proceso escritor es
# justo lo que la hace confiable.
#
# --proxy-headers: detrás del ingress de Container Apps (o de cualquier proxy)
# el visitante real y el esquema https llegan en las cabeceras X-Forwarded-*.
# Sin esto uvicorn cree que todo el tráfico viene del proxy y por http.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PUERTO:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
