"""De qué aparato viene cada pedido.

Un número sorteado que el navegador guarda en una cookie propia y devuelve en
cada visita. **No es una huella del navegador**: no mira fuentes instaladas, ni
resolución, ni nada de lo que sirve para reconocer a una persona en otro sitio.
Es un número al azar que no dice nada de nadie y contesta una sola pregunta, que
es la única que hace falta poder contestar: *¿estas dos entregas salieron del
mismo teléfono?*

Va en una cookie aparte de la de sesión, y ahí está todo el asunto. La de sesión
se vacía al salir —tiene que seguir haciéndolo—, así que cinco cuentas que
entran y salen una atrás de la otra desde el mismo teléfono no dejan, con la
sesión sola, ninguna marca de haber sido el mismo teléfono. Esta sobrevive a
`/salir`, y por eso las junta.

Se puede borrar, y es a propósito que se pueda: quien vacía las cookies del
navegador arranca con un número nuevo y esto no lo ve. Es el techo de lo que se
puede saber desde un servidor sin espiar a nadie, y está bien que sea el techo.
Esto no es un candado —no impide nada ni bloquea a nadie—: es lo que le pone algo
concreto adelante a un educador que, si no, tiene que acusar de memoria.
"""

from __future__ import annotations

import secrets

from fastapi import Request, Response

from app.config import COOKIES_SEGURAS

NOMBRE = "aparato"

# Dos años. Tiene que durar bastante más que el problema que viene a mostrar: una
# cookie que se vence en un mes convierte «el teléfono de siempre» en «un aparato
# nuevo» cada cuatro semanas, y entonces no junta nada con nada.
DURACION = 2 * 365 * 24 * 60 * 60

# 16 bytes al azar. No hace falta más: no hay nada que adivinar del otro lado
# —el número no abre ninguna puerta— y lo único que se le pide es no repetirse.
_BYTES = 16


def nuevo() -> str:
    return secrets.token_hex(_BYTES)


def de(request: Request) -> str:
    """El aparato de este pedido, que dejó puesto el middleware de `app/main.py`.

    Cae en la cookie cruda por si alguna vez se llama desde algo que corre antes
    del middleware. Devuelve cadena vacía si no hay ninguna de las dos: un
    aparato desconocido es un dato que falta, nunca un motivo para no atender.
    """
    return getattr(request.state, "aparato", "") or request.cookies.get(NOMBRE, "")


def sellar(respuesta: Response, aparato: str) -> None:
    """Deja el número puesto en el navegador.

    `httponly` porque ningún JavaScript de la página lo necesita —lo lee el
    servidor y nadie más—, y `samesite=lax` porque no hay un solo pedido desde
    otro sitio que tenga que traerlo.
    """
    respuesta.set_cookie(
        NOMBRE,
        aparato,
        max_age=DURACION,
        httponly=True,
        samesite="lax",
        secure=COOKIES_SEGURAS,
    )
