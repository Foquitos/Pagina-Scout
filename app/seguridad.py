"""Contraseñas: hash con scrypt y freno a la fuerza bruta (stdlib, sin dependencias)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

_N = 2**14
_R = 8
_P = 1
_LARGO = 32


def hashear_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=_LARGO)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${derivada.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        algoritmo, n, r, p, sal_hex, esperado_hex = guardado.split("$")
        if algoritmo != "scrypt":
            return False
        derivada = hashlib.scrypt(
            clave.encode(),
            salt=bytes.fromhex(sal_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(esperado_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivada.hex(), esperado_hex)


# --- Freno a la fuerza bruta ---------------------------------------------------
#
# Los nombres de usuario de una Unidad son adivinables —`ana`, `mateo`, `juanp`—
# y hasta hace poco la contraseña inicial era el propio nombre de usuario: una
# sola prueba por cuenta alcanzaba para entrar en la de cualquiera que todavía no
# la hubiera cambiado. Eso se arregló en `servicios/cuentas.py`, donde ahora la
# provisoria es aleatoria; esto es la otra mitad, la que impide probar en serie.
#
# Va en memoria del proceso. Es lo correcto acá y no una simplificación: la
# aplicación corre con una sola réplica —SQLite quiere un único escritor, ver
# DESPLIEGUE.md— así que no hay un segundo proceso con otro contador. Si algún
# día hay dos, esto hay que mudarlo afuera.

_VENTANA_SEGUNDOS = 15 * 60
_TOPE_POR_USUARIO = 5
# Bastante más alto, porque una Unidad entera puede salir a internet por la misma
# dirección —el wifi del club, la casa donde se juntan— y treinta chicos tecleando
# contraseñas en un celular prestado juntan errores rápido. Para quien barre
# cuentas en serie la diferencia entre 25 y 50 no existe; para la Unidad que se
# quedaría afuera un sábado a la tarde, sí.
_TOPE_POR_IP = 50
# Cota de memoria. Si alguien inventa cien mil usuarios distintos, el diccionario
# no puede crecer sin fin; al llegar acá se tira lo más viejo.
_MAXIMO_CLAVES = 4096

_fallos: dict[str, list[float]] = {}


def _vigentes(clave: str, ahora: float) -> list[float]:
    """Los intentos de esa clave que todavía cuentan, ya descartados los viejos."""
    recientes = [t for t in _fallos.get(clave, ()) if ahora - t < _VENTANA_SEGUNDOS]
    if recientes:
        _fallos[clave] = recientes
    else:
        _fallos.pop(clave, None)
    return recientes


def _podar(ahora: float) -> None:
    for clave in list(_fallos):
        _vigentes(clave, ahora)
    if len(_fallos) > _MAXIMO_CLAVES:
        sobran = sorted(_fallos, key=lambda c: _fallos[c][-1])[: len(_fallos) - _MAXIMO_CLAVES]
        for clave in sobran:
            _fallos.pop(clave, None)


def espera_de_ingreso(usuario: str, ip: str) -> int:
    """Segundos que faltan para poder volver a intentar. 0 si puede intentar ya.

    Se miran dos contadores: el de la cuenta y el de la dirección. El de la
    cuenta es el que de verdad protege —es el que frena probar `ana`/`ana`—; el
    de la dirección frena barrer la Unidad entera con un usuario distinto por
    intento.
    """
    ahora = time.monotonic()
    _podar(ahora)
    for clave, tope in ((f"u:{usuario}", _TOPE_POR_USUARIO), (f"i:{ip}", _TOPE_POR_IP)):
        intentos = _vigentes(clave, ahora)
        if len(intentos) >= tope:
            # Desde el último fallo, no desde el primero: seguir errando dentro
            # del bloqueo lo estira, que es lo que hace que insistir no sirva.
            resta = _VENTANA_SEGUNDOS - (ahora - intentos[-1])
            if resta > 0:
                return int(resta) + 1
    return 0


def anotar_fallo(usuario: str, ip: str) -> None:
    ahora = time.monotonic()
    for clave in (f"u:{usuario}", f"i:{ip}"):
        _fallos.setdefault(clave, []).append(ahora)
    _podar(ahora)


def olvidar_fallos(usuario: str, ip: str) -> None:
    """Entró bien: la cuenta queda limpia.

    La dirección también, y es a propósito: si en esa casa alguien entró bien,
    no es una máquina probando contraseñas, es una familia con dos hermanos.
    """
    _fallos.pop(f"u:{usuario}", None)
    _fallos.pop(f"i:{ip}", None)
