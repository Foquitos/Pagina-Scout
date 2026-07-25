"""Hash de contraseñas con scrypt (stdlib, sin dependencias externas)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

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
