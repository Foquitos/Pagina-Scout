# La imagen de la aplicación. Se arma en dos etapas para que en la final no
# quede ni pip, ni el compilador, ni el código fuente de las dependencias.
#
#   docker build -t retos-unidad .
#   docker run --rm -p 8000:8000 -v retos:/datos-persistentes retos-unidad
#
# Para ponerla en Azure Container Apps, ver DESPLIEGUE.md.

# Probado sobre Python 3.14, que es el piso de requirements.txt.
FROM python:3.14-slim AS constructor

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

# Solo por si alguna dependencia todavía no publicó rueda para 3.14 y pip tiene
# que compilarla. Nada de esto pasa a la imagen final.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --require-virtualenv -r requirements.txt


FROM python:3.14-slim AS aplicacion

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=constructor /opt/venv /opt/venv

WORKDIR /app
COPY main.py ./
COPY app app
COPY datos datos
COPY scripts scripts
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# La base y las fotos van fuera de /app, en un solo directorio: es el único
# lugar que hay que montar en un volumen para que sobrevivan al reinicio del
# contenedor. Todo lo demás es reemplazable con volver a construir la imagen.
ENV BASE_DATOS_URL=sqlite:////datos-persistentes/scout.db \
    DIR_SUBIDAS=/datos-persistentes/uploads \
    PUERTO=8000

# El sed saca los fin de línea de Windows: el script se edita desde ahí y `sh`
# no arranca si el archivo trae \r. Es más barato que confiar en la
# configuración de git de cada máquina.
#
# uid 1000: el mismo número que hay que pasarle al montaje de Azure Files, si no
# el contenedor no escribe en el volumen (ver DESPLIEGUE.md).
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.sh \
 && useradd --uid 1000 --create-home scout \
 && mkdir -p /datos-persistentes/uploads \
 && chown -R scout:scout /datos-persistentes

USER scout
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
