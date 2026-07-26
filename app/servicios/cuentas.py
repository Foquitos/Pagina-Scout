"""Cuentas: altas, contraseñas y blanqueos.

Una sola regla, en un solo lugar: la contraseña inicial de cualquier cuenta
—joven o educador— es su propio nombre de usuario, y mientras siga siendo esa
la cuenta no sirve para nada más que para cambiarla. El educador que da de alta
a alguien le dice «tu usuario es `ana` y tu contraseña también»: no tiene que
inventar contraseñas para otros, ni anotarlas en un papel, ni dictarlas en la
reunión, y nadie termina usando una que eligió un tercero.

El blanqueo es exactamente el mismo movimiento —volver al día uno—, así que
comparte el cuerpo con el alta: si un día cambia cómo arranca una cuenta,
cambia para las dos. Es el único camino de recuperación que hay, y a propósito:
no pedimos direcciones de correo de menores, así que la contraseña olvidada se
resuelve donde se conocen las caras, no por mail.

Quién puede blanquear a quién es una cuestión de permisos y vive en el router
(`app/routers/educador.py`). Acá está el qué.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Usuario
from app.seguridad import hashear_clave, verificar_clave

# Corto a propósito. Del otro lado hay chicas y chicos de 11 a 15 años entrando
# desde el celular de la familia: una regla larga y con símbolos termina escrita
# en la tapa de la mochila, que es peor que una contraseña corta. Lo que de
# verdad protege la cuenta es que la inicial no sirva para nada.
LARGO_MINIMO = 6

# El nombre de usuario también es la contraseña inicial, así que tiene que poder
# tipearse sin pelearse con el teclado del celular: sin espacios, sin acentos y
# sin mayúsculas que después nadie recuerda si iban.
_LOGIN_VALIDO = re.compile(r"^[a-z0-9][a-z0-9._-]{1,29}$")


class DatoInvalido(Exception):
    """No se puede hacer eso. El motivo está escrito para mostrarlo tal cual."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def normalizar_login(texto: str) -> str:
    """El nombre de usuario como se guarda y como se busca."""
    return texto.strip().lower()


def establecer_provisoria(usuario: Usuario, clave: str | None = None) -> None:
    """Deja una contraseña provisoria y la obligación de cambiarla al entrar.

    Sin `clave`, la provisoria es el propio nombre de usuario: es el caso normal
    —el alta y el blanqueo—. Se puede pasar otra desde la consola, y sigue
    siendo provisoria igual, porque el punto no es que sea fácil de adivinar
    sino que la eligió alguien que no es el dueño de la cuenta.
    """
    usuario.hash_clave = hashear_clave(clave or usuario.usuario)
    usuario.debe_cambiar_clave = True


def alta(sesion: Session, login: str, nombre: str, rol: str, **campos) -> Usuario:
    """Crea una cuenta con su contraseña inicial. No hace commit.

    `**campos` es lo que cambia según el rol —unidad, patrulla, etapa—. Lo que
    no cambia nunca es cómo arranca la contraseña, y por eso el alta pasa por
    acá y no se arma un `Usuario` a mano en cada router.
    """
    login = normalizar_login(login)
    if not _LOGIN_VALIDO.match(login):
        raise DatoInvalido(
            "El usuario va en minúsculas, sin espacios ni acentos: letras, "
            "números, puntos, guiones. Es lo que va a tener que tipear en el celular."
        )
    if not nombre.strip():
        raise DatoInvalido("Falta el nombre de la persona.")
    if sesion.scalar(select(Usuario.id).where(Usuario.usuario == login)) is not None:
        raise DatoInvalido(f"El usuario «{login}» ya existe.")

    usuario = Usuario(usuario=login, nombre=nombre.strip(), rol=rol, **campos)
    establecer_provisoria(usuario)
    sesion.add(usuario)
    return usuario


def blanquear(usuario: Usuario) -> None:
    """Vuelve la cuenta al día uno: la contraseña pasa a ser su nombre de usuario.

    Lo que se hace cuando alguien se la olvidó. La sesión que tuviera abierta no
    se corta —no hace falta: al entrar de nuevo la va a tener que cambiar—, y
    quien blanquea no se enteró de la contraseña vieja en ningún momento.
    """
    establecer_provisoria(usuario)


def cambiar_clave(usuario: Usuario, actual: str, nueva: str, repetida: str) -> None:
    """Cambia la contraseña de la propia cuenta. No hace commit.

    La actual se pide siempre, también en el primer cambio obligado. No es
    burocracia: es lo que evita que una sesión abierta y sin dueño —el celular
    que quedó dando vueltas en la mesa de la reunión— se quede con la cuenta.
    """
    if not verificar_clave(actual, usuario.hash_clave):
        raise DatoInvalido("La contraseña actual no es esa.")
    if nueva != repetida:
        raise DatoInvalido("Las dos contraseñas nuevas no coinciden.")
    if len(nueva) < LARGO_MINIMO:
        raise DatoInvalido(
            f"La contraseña nueva necesita al menos {LARGO_MINIMO} caracteres."
        )
    if nueva != nueva.strip():
        raise DatoInvalido(
            "La contraseña no puede empezar ni terminar con un espacio: "
            "es imposible darse cuenta cuando no entra."
        )
    if normalizar_login(nueva) == usuario.usuario:
        raise DatoInvalido(
            "Esa es la contraseña con la que te dieron de alta: elegí una "
            "distinta de tu usuario."
        )
    if verificar_clave(nueva, usuario.hash_clave):
        raise DatoInvalido("Esa ya es tu contraseña. Poné una nueva.")

    usuario.hash_clave = hashear_clave(nueva)
    usuario.debe_cambiar_clave = False
