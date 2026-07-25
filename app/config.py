"""Configuración de la aplicación, leída de variables de entorno."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent

# Zona horaria con la que se decide "qué día es hoy" para los retos diarios.
ZONA_HORARIA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

BASE_DATOS_URL = os.environ.get("BASE_DATOS_URL", f"sqlite:///{RAIZ / 'scout.db'}")

# En producción hay que definir CLAVE_SECRETA sí o sí: sin ella las sesiones
# firmadas se invalidan en cada reinicio.
CLAVE_SECRETA = os.environ.get("CLAVE_SECRETA", "desarrollo-inseguro-cambiar")

DIR_SUBIDAS = Path(os.environ.get("DIR_SUBIDAS", RAIZ / "uploads"))
DIR_DATOS = RAIZ / "datos"
DIR_PLANTILLAS = RAIZ / "app" / "templates"
DIR_ESTATICOS = RAIZ / "app" / "static"

# Validador de evidencias activo: "manual" | "simulado".
# Ver app/servicios/validacion.py para el contrato y cómo sumar uno nuevo.
VALIDADOR = os.environ.get("VALIDADOR", "simulado")

# Tope de lo que se acepta *subir*. Lo que queda guardado es mucho menos: toda
# foto se reescribe a JPEG antes de tocar el disco (ver servicios/medios.py).
MAX_BYTES_FOTO = int(os.environ.get("MAX_BYTES_FOTO", 8 * 1024 * 1024))
EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

# Lado mayor al que se reduce cada foto, y calidad del JPEG resultante. Con
# 1600/82 una foto de celular de 4 MB queda en 250-350 kB: alcanza para verla
# en pantalla y para imprimirla chica, que es lo que un Libro de Oro necesita.
FOTO_LADO_MAXIMO = int(os.environ.get("FOTO_LADO_MAXIMO", 1600))
FOTO_CALIDAD = int(os.environ.get("FOTO_CALIDAD", 82))

PUNTAJE_POR_DEFECTO = int(os.environ.get("PUNTAJE_POR_DEFECTO", 10))
