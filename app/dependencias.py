"""Dependencias comunes: usuario de sesión, guardas por rol y plantillas."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import DIR_PLANTILLAS
from app.db import obtener_sesion
from app.models import ETAPAS_NOMBRE, Usuario
from app.servicios.medios import video_guardado

plantillas = Jinja2Templates(directory=str(DIR_PLANTILLAS))
plantillas.env.globals["ETAPAS_NOMBRE"] = ETAPAS_NOMBRE
# La URL del reproductor la arma el servicio, nunca la plantilla con texto crudo.
plantillas.env.globals["video"] = video_guardado


class RedireccionAIngreso(Exception):
    """Se levanta cuando una página web necesita sesión y no la hay."""

    def __init__(self, destino: str = "/ingresar"):
        self.destino = destino


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


def usuario_actual(usuario: Usuario | None = Depends(usuario_opcional)) -> Usuario:
    if usuario is None:
        raise RedireccionAIngreso()
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


def redirigir(destino: str) -> RedirectResponse:
    """Redirección tras un POST: 303 para que el navegador use GET."""
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)
