"""Dependencias comunes: usuario de sesión, guardas por rol y plantillas."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import DIR_PLANTILLAS
from app.db import obtener_sesion
from app.models import ETAPAS_NOMBRE, Usuario
from app.servicios.cuentas import LARGO_MINIMO
from app.servicios.medios import video_guardado

plantillas = Jinja2Templates(directory=str(DIR_PLANTILLAS))
plantillas.env.globals["ETAPAS_NOMBRE"] = ETAPAS_NOMBRE
# La URL del reproductor la arma el servicio, nunca la plantilla con texto crudo.
plantillas.env.globals["video"] = video_guardado
# El largo mínimo lo dice la pantalla y lo aplica el servicio: sale del mismo
# número para que no puedan contradecirse.
plantillas.env.globals["largo_minimo"] = LARGO_MINIMO


# Paleta de los avatares. Son los colores del programa: el avatar de alguien es
# siempre el mismo porque sale de su nombre, no de un sorteo.
_COLORES_AVATAR = ("#3E8E5A", "#2E86AB", "#E0A526", "#D64550", "#7d5ba6", "#E2673A")


def color_de(texto: str) -> str:
    """Un color estable a partir de un texto, para los avatares."""
    return _COLORES_AVATAR[sum(map(ord, texto or "?")) % len(_COLORES_AVATAR)]


def iniciales(nombre: str) -> str:
    """«Ana Paula Díaz» → «AP». Lo que va adentro del círculo del avatar."""
    partes = (nombre or "").split()
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[1][0]).upper()


def primer_nombre(nombre: str) -> str:
    """«Ana Paula Díaz» → «Ana». Lo que entra al lado del avatar en el celular."""
    partes = (nombre or "").split()
    return partes[0] if partes else ""


plantillas.env.globals["color_de"] = color_de
plantillas.env.globals["iniciales"] = iniciales
plantillas.env.globals["primer_nombre"] = primer_nombre


class Redireccion(Exception):
    """Antes de esta página hay que pasar por otra. La atiende `app/main.py`."""

    def __init__(self, destino: str):
        super().__init__(destino)
        self.destino = destino


class RedireccionAIngreso(Redireccion):
    """Se levanta cuando una página web necesita sesión y no la hay."""

    def __init__(self, destino: str = "/ingresar"):
        super().__init__(destino)


class DebeCambiarClave(Redireccion):
    """Hay sesión, pero la cuenta sigue con la contraseña con la que se dio de alta.

    No es un error: es la mitad del alta que le toca a la persona. Hasta que la
    haga, todo lo demás la manda a `/clave`.
    """

    def __init__(self, destino: str = "/clave"):
        super().__init__(destino)


def usuario_opcional(
    request: Request, sesion: Session = Depends(obtener_sesion)
) -> Usuario | None:
    id_usuario = request.session.get("usuario_id")
    if id_usuario is None:
        return None
    usuario = sesion.get(Usuario, id_usuario)
    if usuario is None or not usuario.activo:
        request.session.clear()
        return None
    return usuario


def usuario_de_sesion(usuario: Usuario | None = Depends(usuario_opcional)) -> Usuario:
    """Hay sesión, y no se le pide nada más.

    La usa `/clave` y nadie más: es la única página a la que se llega con la
    contraseña con la que te dieron de alta.
    """
    if usuario is None:
        raise RedireccionAIngreso()
    return usuario


def usuario_actual(usuario: Usuario = Depends(usuario_de_sesion)) -> Usuario:
    """Hay sesión y la cuenta ya tiene una contraseña que eligió su dueño.

    El corte está acá, en la dependencia de la que cuelgan todas las demás, y no
    ruta por ruta: una pantalla nueva queda cubierta sin que nadie se tenga que
    acordar de sumarla.
    """
    if usuario.debe_cambiar_clave:
        raise DebeCambiarClave()
    return usuario


def solo_educador(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if not usuario.es_educador:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta sección es del equipo de educadores.",
        )
    return usuario


def solo_joven(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if usuario.es_educador:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta sección es de las y los jóvenes de la Unidad.",
        )
    return usuario


def render(request: Request, plantilla: str, **contexto):
    contexto.setdefault("usuario", None)
    return plantillas.TemplateResponse(request, plantilla, contexto)


def quiere_json(request: Request) -> bool:
    """El pedido lo hizo `app.js` y espera datos, no una página entera.

    La cabecera la manda solo el JavaScript; un formulario común nunca la
    trae. Así la misma ruta atiende a los dos sin duplicarse, y si mañana
    alguien entra sin JavaScript sigue funcionando como el primer día.
    """
    return request.headers.get("x-sin-recarga") == "json"


def fragmento(plantilla: str, **contexto) -> str:
    """Arma un pedazo de página para que el JavaScript lo pegue en su lugar.

    El HTML lo sigue escribiendo Jinja. El listado que se repinta sin
    recargar y el que se ve al entrar salen de la misma plantilla, así que
    no hay forma de que se despeguen.
    """
    return plantillas.get_template(plantilla).render(**contexto)


def redirigir(destino: str) -> RedirectResponse:
    """Redirección tras un POST: 303 para que el navegador use GET."""
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)
