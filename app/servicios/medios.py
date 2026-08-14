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
from datetime import datetime
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


# --- Lo que la foto cuenta de sí misma ----------------------------------------
#
# Una foto sacada con un teléfono trae adentro la marca y el modelo de la cámara
# y la fecha en que se apretó el botón. Una imagen generada por una IA no trae
# nada de eso, y encima suele traer lo contrario: el sello C2PA que OpenAI,
# Google y Adobe le ponen a propósito a lo que fabrican, para que se sepa.
#
# Esto se lee **antes** de guardar, porque al guardar se borra todo (ver
# `guardar_foto`: sin `exif=`, y por el GPS). De todo lo que trae se conservan
# tres cosas —cámara, cuándo, con qué software— y ni un byte más: la ubicación
# de dónde vive un chico sigue sin tocar el disco, que era la razón de borrarlo.
#
# **Nada de esto prueba nada.** WhatsApp le borra los metadatos a todo lo que
# pasa por él, así que una foto de verdad reenviada por ahí llega tan pelada como
# una inventada, y una captura de pantalla también. Es una señal para que la mire
# una persona, y así se muestra.


@dataclass(frozen=True)
class SenalesFoto:
    """Lo que se pudo leer. Todo vacío significa «no traía nada», no «es falsa»."""

    camara: str = ""
    tomada_en: datetime | None = None
    software: str = ""
    generada: bool = False


# Los números de las etiquetas EXIF que interesan. Son los del estándar y no
# cambian; Pillow los expone tal cual.
_MARCA, _MODELO, _SOFTWARE, _FECHA = 271, 272, 305, 306
_SUBIFD_EXIF, _FECHA_ORIGINAL = 0x8769, 36867

# Lo que dejan escrito los generadores, en minúsculas. `trainedalgorithmicmedia`
# es el valor IPTC con el que una imagen declara haber salido de un modelo: es el
# más confiable de todos porque lo pone el propio generador para que se sepa.
_SELLOS_DE_IA = (
    b"trainedalgorithmicmedia",
    b"stable diffusion",
    b"stablediffusion",
    b"midjourney",
    b"dall-e",
    b"dalle",
    b"openai",
    b"comfyui",
    b"automatic1111",
    b"novelai",
    b"ideogram",
    b"firefly",
)
# El contenedor de procedencia. **No significa IA por sí solo**: hay cámaras
# —Leica, algunas Sony— que lo usan justamente para firmar que la foto es de
# verdad. Por eso solo cuenta cuando la foto no trae datos de cámara.
_SELLOS_DE_PROCEDENCIA = (b"c2pa", b"jumbf")

# Los programas de difusión que se instalan en la propia máquina no firman nada,
# pero guardan en el PNG la receta con la que armaron la imagen. Ahí no está el
# nombre del programa: está la receta, y estas dos palabras juntas no aparecen en
# ninguna otra parte. Van de a pares porque cada una suelta es demasiado común.
_RECETA_DE_DIFUSION = (b"steps:", b"sampler:")
_RECETA_DE_COMFYUI = (b"class_type", b"prompt\x00")

_SOFTWARE_DE_IA = (
    "dall", "openai", "midjourney", "stable diffusion", "firefly",
    "comfyui", "novelai", "ideogram", "flux", "gemini",
)

# Cuánto se mira. Los bloques de metadatos van pegados al principio del archivo:
# con esto sobra, y acota el trabajo de recorrer algo que subió otro.
_TOPE_METADATOS = 1024 * 1024


def senales_de_foto(contenido: bytes) -> SenalesFoto:
    """Lee lo que la foto trae adentro. **Nunca levanta.**

    Una foto que no se puede inspeccionar se sube igual y no deja señales. Al
    revés —que una cámara rara o un archivo raro le impidan entregar a un chico—
    sería muchísimo peor que no saber de dónde salió una foto.

    Se le puede pasar el archivo entero o solo su cabecera: `Image.open` lee el
    encabezado sin descomprimir nada, y los metadatos viven al principio. Eso es
    lo que permite mirar el original cuando lo que se sube es la copia achicada
    en el celular, que ya viene sin nada (ver `app/static/app.js`).
    """
    recorte = contenido[:_TOPE_METADATOS]
    camara, tomada_en, software = _exif(recorte)
    return SenalesFoto(
        camara=camara,
        tomada_en=tomada_en,
        software=software,
        generada=_tiene_sello_de_ia(recorte, hay_camara=bool(camara))
        or any(nombre in software.lower() for nombre in _SOFTWARE_DE_IA),
    )


def _exif(contenido: bytes) -> tuple[str, datetime | None, str]:
    """Cámara, cuándo se tomó y con qué software, de las etiquetas EXIF."""
    try:
        with Image.open(BytesIO(contenido)) as imagen:
            exif = imagen.getexif()
            if not exif:
                return "", None, ""
            marca = _texto(exif.get(_MARCA))
            modelo = _texto(exif.get(_MODELO))
            software = _texto(exif.get(_SOFTWARE))
            # `DateTimeOriginal` —cuándo se apretó el botón— vive en el sub-IFD;
            # `DateTime` en el principal es cuándo se modificó el archivo, que no
            # es lo mismo y sirve de respaldo cuando el primero no está.
            crudo = exif.get_ifd(_SUBIFD_EXIF).get(_FECHA_ORIGINAL) or exif.get(_FECHA)
    except Exception:  # noqa: BLE001 — inspeccionar una foto no puede romper una entrega
        return "", None, ""

    # El modelo suele repetir la marca («Apple» / «iPhone 13»), y a veces no.
    camara = modelo if modelo.lower().startswith(marca.lower()) else f"{marca} {modelo}"
    return camara.strip()[:120], _fecha_exif(crudo), software


def _texto(valor) -> str:
    """Una etiqueta EXIF como texto. Hay cámaras que las escriben en bytes crudos."""
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "replace")
    # El \x00 del final es habitual en las etiquetas de texto del EXIF.
    return str(valor).replace("\x00", "").strip()[:120]


def _fecha_exif(crudo) -> datetime | None:
    """«2026:08:13 19:04:22» → datetime. None si viene vacío o ilegible."""
    if not crudo:
        return None
    try:
        return datetime.strptime(str(crudo).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _tiene_sello_de_ia(contenido: bytes, hay_camara: bool) -> bool:
    bloques = _metadatos(contenido).lower()
    if not bloques:
        return False
    if any(sello in bloques for sello in _SELLOS_DE_IA):
        return True
    if all(marca in bloques for marca in _RECETA_DE_DIFUSION):
        return True
    if all(marca in bloques for marca in _RECETA_DE_COMFYUI):
        return True
    return not hay_camara and any(s in bloques for s in _SELLOS_DE_PROCEDENCIA)


def _metadatos(contenido: bytes) -> bytes:
    """Los bloques de metadatos del archivo, sin los píxeles.

    Se recorre la estructura del formato en vez de buscar el sello en el archivo
    entero, y la diferencia importa: los datos comprimidos de una foto de verdad
    son ruido, y en un megabyte de ruido cuatro letras aparecen por casualidad.
    Un falso «generada» manda a la cola del educador la entrega honesta de
    alguien, así que el sello se busca donde los sellos viven y en ningún otro
    lado. De un formato que no se reconoce se devuelve vacío: sin señal es mejor
    que con una inventada.
    """
    try:
        if contenido[:2] == b"\xff\xd8":
            return _bloques_jpeg(contenido)
        if contenido[:8] == b"\x89PNG\r\n\x1a\n":
            return _bloques_png(contenido)
        if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
            return _bloques_webp(contenido)
    except Exception:  # noqa: BLE001 — un archivo cortado o raro no deja señal, y ya
        return b""
    return b""


def _bloques_jpeg(contenido: bytes) -> bytes:
    """Los segmentos APPn y los comentarios, hasta donde arrancan los píxeles."""
    partes: list[bytes] = []
    i, largo = 2, len(contenido)
    while i + 4 <= largo:
        if contenido[i] != 0xFF:
            break
        marcador = contenido[i + 1]
        # Los que no llevan tamaño: relleno, reinicios y el arranque.
        if marcador in (0xFF, 0x01, 0xD8) or 0xD0 <= marcador <= 0xD7:
            i += 2
            continue
        # SOS y EOI: de acá para adelante son píxeles.
        if marcador in (0xDA, 0xD9):
            break
        tamano = int.from_bytes(contenido[i + 2 : i + 4], "big")
        if tamano < 2:
            break
        if 0xE0 <= marcador <= 0xEF or marcador == 0xFE:
            partes.append(contenido[i + 4 : i + 2 + tamano])
        i += 2 + tamano
    return b"".join(partes)


def _bloques_png(contenido: bytes) -> bytes:
    """Los trozos de texto y metadatos, hasta el primer IDAT."""
    partes: list[bytes] = []
    i, largo = 8, len(contenido)
    while i + 8 <= largo:
        tamano = int.from_bytes(contenido[i : i + 4], "big")
        tipo = contenido[i + 4 : i + 8]
        if tipo == b"IDAT":
            break
        if tipo not in (b"IHDR", b"PLTE"):
            partes.append(tipo + contenido[i + 8 : i + 8 + tamano])
        # 8 de encabezado, el dato, y 4 del código de control del final.
        i += 12 + tamano
    return b"".join(partes)


def _bloques_webp(contenido: bytes) -> bytes:
    """Los trozos RIFF que no son la imagen en sí."""
    partes: list[bytes] = []
    i, largo = 12, len(contenido)
    imagen = (b"VP8 ", b"VP8L", b"VP8X", b"ANMF", b"ALPH")
    while i + 8 <= largo:
        tipo = contenido[i : i + 4]
        tamano = int.from_bytes(contenido[i + 4 : i + 8], "little")
        if tipo not in imagen:
            partes.append(tipo + contenido[i + 8 : i + 8 + tamano])
        # Los trozos se alinean a par: uno de tamaño impar lleva un byte de más.
        i += 8 + tamano + (tamano & 1)
    return b"".join(partes)


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
