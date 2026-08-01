"""Cuentas: altas, contraseñas y blanqueos.

Una sola regla, en un solo lugar: la contraseña inicial de cualquier cuenta
—joven o educador— es **provisoria y aleatoria**, y mientras siga siendo esa la
cuenta no sirve para nada más que para cambiarla. La pantalla del alta la
muestra una vez para que el educador se la diga a la persona ahí mismo.

Antes la provisoria era el propio nombre de usuario, y la razón era buena: el
educador no tenía que inventar contraseñas para otros ni anotarlas en un papel.
El problema es que los nombres de usuario de una Unidad son adivinables —`ana`,
`mateo`, `juanp`— y en una aplicación abierta a internet eso convertía cada
cuenta recién dada de alta en una puerta de una sola prueba. Un freno a la
fuerza bruta no ayuda contra un ataque que acierta en el primer intento: había
que cambiar la provisoria. El freno está igual, en `app/seguridad.py`, para lo
demás.

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
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import hay_referencias_a
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


# De acá salen las provisorias. Palabras cortas, sin acentos y sin letras que se
# confundan al dictarlas en una reunión con ruido: nada de b/v ni de c/s/z en el
# lugar donde se juegan la diferencia. Se dicen en voz alta una vez y se tipean
# en el teclado de un celular, ese es todo el requisito.
_PALABRAS = (
    "carpa", "fogata", "nudo", "brujula", "mochila", "linterna", "mapa", "remo",
    "sendero", "rio", "monte", "puente", "estrella", "lupa", "pala", "hacha",
    "olla", "manta", "pino", "roble", "halcon", "puma", "zorro", "condor",
    "tigre", "lobo", "gaviota", "delfin", "aguila", "jaguar", "norte", "sur",
    "farol", "tronco", "piedra", "arroyo", "cumbre", "valle", "duna", "faro",
)


def provisoria() -> str:
    """Una contraseña de un solo uso, fácil de dictar y difícil de adivinar.

    Dos palabras y dos dígitos: `fogata-remo-47`. Son 40×40×100 = 160.000
    combinaciones, que contra el freno de cinco intentos de `app/seguridad.py`
    es de sobra —y sirve para las horas que pasan entre el alta y el primer
    ingreso, que es todo lo que tiene que durar.
    """
    return (
        f"{secrets.choice(_PALABRAS)}-{secrets.choice(_PALABRAS)}-"
        f"{secrets.randbelow(90) + 10}"
    )


def establecer_provisoria(usuario: Usuario, clave: str | None = None) -> str:
    """Deja una contraseña provisoria y la obligación de cambiarla al entrar.

    Devuelve la contraseña en claro, y es la única vez que existe fuera del
    hash: quien llama tiene que mostrarla en pantalla para que el educador se la
    diga a su dueño. No se guarda en ningún lado ni se puede volver a ver.

    Sin `clave`, se sortea una. Se puede pasar otra desde la consola, y sigue
    siendo provisoria igual, porque el punto no es cuánto cuesta adivinarla sino
    que la eligió alguien que no es el dueño de la cuenta.
    """
    en_claro = clave or provisoria()
    usuario.hash_clave = hashear_clave(en_claro)
    usuario.debe_cambiar_clave = True
    return en_claro


def alta(sesion: Session, login: str, nombre: str, rol: str, **campos) -> tuple[Usuario, str]:
    """Crea una cuenta con su contraseña inicial. No hace commit.

    Devuelve la cuenta y su contraseña provisoria en claro, para mostrarla una
    vez. `**campos` es lo que cambia según el rol —unidad, patrulla, etapa—. Lo
    que no cambia nunca es cómo arranca la contraseña, y por eso el alta pasa
    por acá y no se arma un `Usuario` a mano en cada router.
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
    en_claro = establecer_provisoria(usuario)
    sesion.add(usuario)
    return usuario, en_claro


def blanquear(usuario: Usuario) -> str:
    """Vuelve la cuenta al día uno con una provisoria nueva. Devuelve cuál.

    Lo que se hace cuando alguien se la olvidó. La sesión que tuviera abierta no
    se corta —no hace falta: al entrar de nuevo la va a tener que cambiar—, y
    quien blanquea no se enteró de la contraseña vieja en ningún momento.
    """
    return establecer_provisoria(usuario)


# --- Bajas ---------------------------------------------------------------------
#
# Sacar a alguien del equipo son dos cosas distintas según lo que esa cuenta haya
# hecho, y la diferencia importa:
#
# **Alguien que trabajó en la Unidad se da de baja, no se borra.** Un educador
# firma cosas: la carta que acordó, el cambio de etapa que decidió, la entrega
# que validó, la página que bajó del libro. Todo eso queda con su nombre porque
# la aplicación entera está construida sobre que se sepa quién decidió qué.
# Borrar la cuenta borraría esas firmas —o dejaría huecos donde había un nombre—,
# y el historial de progresión de un chico dejaría de decir quién estuvo.
#
# **Una cuenta que no dejó rastro se borra de verdad.** El usuario que se escribió
# mal, el educador que se dio de alta dos veces. Esa cuenta no existió para nadie
# y dejarla como «inactiva» en una lista es guardar basura con nombre de persona.
#
# No hay que elegir a mano: se mira la base y se hace lo que corresponde.


def dejo_rastro(sesion: Session, usuario_id: int) -> bool:
    """¿Hay alguna fila en toda la base que apunte a esta persona?

    El recorrido del esquema vive en `app/db.py` porque sirve igual para una
    patrulla; acá queda el nombre que se lee bien desde una pantalla de cuentas.
    """
    return hay_referencias_a(sesion, "usuarios", usuario_id)


def dar_de_baja(sesion: Session, usuario: Usuario) -> bool:
    """Saca a alguien de la Unidad. Devuelve True si además se borró la cuenta.

    No hace commit. La sesión que la persona tuviera abierta se corta sola en el
    pedido siguiente: `usuario_opcional` la vacía al ver la cuenta inactiva, y
    `/ingresar` tampoco la deja volver a entrar.
    """
    if dejo_rastro(sesion, usuario.id):
        usuario.activo = False
        return False
    sesion.delete(usuario)
    return True


def reincorporar(usuario: Usuario) -> None:
    """Vuelve al equipo. Su contraseña es la que tenía: la baja no la tocó.

    Existe porque una baja por error tiene que arreglarse desde la pantalla. Si
    la persona además se olvidó la contraseña, se blanquea aparte.
    """
    usuario.activo = True


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
            "Tu contraseña no puede ser tu nombre de usuario: es lo primero "
            "que probaría cualquiera."
        )
    if verificar_clave(nueva, usuario.hash_clave):
        raise DatoInvalido("Esa ya es tu contraseña. Poné una nueva.")

    usuario.hash_clave = hashear_clave(nueva)
    usuario.debe_cambiar_clave = False
