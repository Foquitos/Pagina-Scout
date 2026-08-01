"""Fotos y videos: todo lo que entra por un formulario y ocupa disco.

Dos reglas, las dos por la misma razón —que una Unidad entera quepa en un
servidor chico—:

**Ninguna foto se guarda como vino.** Se reescribe a JPEG con el lado mayor
acotado antes de tocar el disco. Una foto de celular de 4 MB queda en 250-350 kB,
que en pantalla se ve igual. El original no se conserva: no hay a dónde volver,
y es a propósito.

**Ningún video se guarda.** Un minuto de video de celular pesa más que el Libro
de Oro entero de un año. Se guarda el enlace a YouTube o Vimeo y se muestra el
reproductor de ellos: cero bytes en el servidor y cero ancho de banda al servir.

El enlace nunca se mete crudo en el `iframe`. Se extrae el identificador, se
valida contra una expresión estricta y la URL de reproducción la arma esta
función. Un `src` armado con texto de un formulario es una puerta abierta.

Y dos topes, porque lo que entra por un formulario lo elige otro: nunca se lee
más de `MAX_BYTES_FOTO` en memoria (`leer_subida`) y nunca se descomprime una
imagen de más de `MAX_PIXELES_FOTO` píxeles. El segundo no es paranoia: el peso
del archivo no dice nada de lo que ocupa abierto.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import (
    DIR_SUBIDAS,
    EXTENSIONES_FOTO,
    FOTO_CALIDAD,
    FOTO_LADO_MAXIMO,
    MAX_BYTES_FOTO,
    MAX_PIXELES_FOTO,
)

if TYPE_CHECKING:  # pragma: no cover — solo para el tipo, no en tiempo de ejecución
    from fastapi import UploadFile


class MedioInvalido(Exception):
    """Lo que subieron no sirve, con un motivo que se le puede mostrar a un chico."""


# --- Fotos --------------------------------------------------------------------


def leer_subida(archivo: UploadFile, tope: int = MAX_BYTES_FOTO) -> bytes:
    """Lee lo que subieron sin pasar de `tope` bytes en memoria.

    `archivo.file.read()` a secas trae el archivo entero antes de que nadie mire
    el tamaño: un celular puede mandar 300 MB y el contenedor tiene 0,5 GiB.
    Leyendo de a pedazos, lo que no entra se corta y nunca se reserva.

    Esto acota la **memoria**, que es lo que tira el proceso abajo. El cuerpo de
    la petición ya lo escribió Starlette en un temporal antes de llegar acá; de
    eso se ocupa el tope de `MAX_BYTES_PETICION` en `app/main.py`, que mira el
    Content-Length y rechaza antes de leer nada.
    """
    trozos: list[bytes] = []
    total = 0
    while True:
        trozo = archivo.file.read(64 * 1024)
        if not trozo:
            break
        total += len(trozo)
        if total > tope:
            raise MedioInvalido(
                f"La foto es demasiado grande (máximo {tope // (1024 * 1024)} MB)."
            )
        trozos.append(trozo)
    return b"".join(trozos)


def guardar_foto(nombre_original: str | None, contenido: bytes) -> str:
    """Comprime y guarda. Devuelve el nombre del archivo dentro de DIR_SUBIDAS."""
    extension = Path(nombre_original or "").suffix.lower()
    if extension not in EXTENSIONES_FOTO:
        raise MedioInvalido(
            f"Formato de imagen no admitido: {extension or 'sin extensión'}. "
            "Sirven jpg, png y webp."
        )
    if len(contenido) > MAX_BYTES_FOTO:
        tope = MAX_BYTES_FOTO // (1024 * 1024)
        raise MedioInvalido(f"La foto es demasiado grande (máximo {tope} MB).")

    try:
        # `open` lee el encabezado y nada más: acá todavía no se reservó el mapa
        # de bits, así que se pueden mirar las medidas antes de que cueste algo.
        imagen = Image.open(BytesIO(contenido))
        ancho, alto = imagen.size
        if ancho * alto > MAX_PIXELES_FOTO:
            raise MedioInvalido(
                f"Esa imagen es enorme ({ancho}×{alto}). Mandá una foto normal "
                "de la cámara del celular."
            )
        imagen.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        # Cae acá el .heic de iPhone si Pillow no lo puede abrir. Casi siempre
        # Safari lo convierte a JPEG antes de subirlo, pero no siempre.
        #
        # `DecompressionBombError` no hereda de OSError, así que sin nombrarla
        # se escapaba de este `except` y salía un 500 en vez de un motivo.
        raise MedioInvalido(
            "No pudimos abrir esa imagen. Si la sacaste con un iPhone, "
            "probá exportarla como JPG."
        ) from error

    # Las fotos de celular vienen derechas por metadato, no por píxeles.
    imagen = ImageOps.exif_transpose(imagen)
    if imagen.mode not in ("RGB", "L"):
        imagen = imagen.convert("RGB")
    imagen.thumbnail((FOTO_LADO_MAXIMO, FOTO_LADO_MAXIMO), Image.LANCZOS)

    DIR_SUBIDAS.mkdir(parents=True, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.jpg"
    # Sin exif=: el EXIF trae GPS. No queremos guardar dónde vive un chico.
    imagen.save(DIR_SUBIDAS / nombre, "JPEG", quality=FOTO_CALIDAD, optimize=True)
    return nombre


def borrar_foto(nombre: str | None) -> None:
    """Best effort: si el archivo ya no está, no es un problema."""
    if not nombre:
        return
    ruta = DIR_SUBIDAS / Path(nombre).name
    ruta.unlink(missing_ok=True)


# --- Videos -------------------------------------------------------------------


@dataclass(frozen=True)
class Video:
    servicio: str
    identificador: str

    @property
    def embed(self) -> str:
        if self.servicio == "youtube":
            # -nocookie: no le planta cookies de seguimiento a un chico de 12.
            return f"https://www.youtube-nocookie.com/embed/{self.identificador}"
        return f"https://player.vimeo.com/video/{self.identificador}"

    @property
    def url(self) -> str:
        if self.servicio == "youtube":
            return f"https://www.youtube.com/watch?v={self.identificador}"
        return f"https://vimeo.com/{self.identificador}"


_HOSTS_YOUTUBE = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be",
}
_HOSTS_VIMEO = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}

_ID_YOUTUBE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ID_VIMEO = re.compile(r"^\d{6,12}$")

_NO_RECONOCIDO = (
    "Por ahora reconocemos videos de YouTube y de Vimeo. Subilo ahí como "
    "«no listado» y pegá el enlace acá: así solo lo ve quien tiene el link."
)


def leer_video(url: str) -> Video | None:
    """Reconoce un enlace de YouTube o Vimeo. Devuelve None si viene vacío.

    Se parsea la URL y se compara el **host** contra una lista blanca. Buscar
    "youtu.be/xxx" en cualquier parte del texto no alcanza: `https://otro.sitio/
    youtu.be/xxx.mp4` la pasaría, y terminaríamos embebiendo un video que no es
    el que pegaron.
    """
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = f"https://{url}"

    try:
        partes = urlparse(url)
        host = (partes.hostname or "").lower()
    except ValueError as error:
        raise MedioInvalido(_NO_RECONOCIDO) from error

    if partes.scheme not in ("http", "https"):
        raise MedioInvalido(_NO_RECONOCIDO)

    camino = [t for t in partes.path.split("/") if t]

    if host in _HOSTS_YOUTUBE:
        if host.endswith("youtu.be"):
            candidato = camino[0] if camino else ""
        elif camino and camino[0] in ("embed", "shorts", "live", "v"):
            candidato = camino[1] if len(camino) > 1 else ""
        else:
            candidato = parse_qs(partes.query).get("v", [""])[0]
        if _ID_YOUTUBE.match(candidato):
            return Video("youtube", candidato)

    elif host in _HOSTS_VIMEO:
        for tramo in reversed(camino):
            if _ID_VIMEO.match(tramo):
                return Video("vimeo", tramo)

    raise MedioInvalido(_NO_RECONOCIDO)


def video_guardado(servicio: str | None, identificador: str | None) -> Video | None:
    """Rehidrata lo que quedó en la base, sin volver a validar."""
    if not servicio or not identificador:
        return None
    return Video(servicio, identificador)
