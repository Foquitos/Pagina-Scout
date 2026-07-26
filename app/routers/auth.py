"""Ingreso, salida y la contraseña de la propia cuenta."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, usuario_de_sesion, usuario_opcional
from app.models import Usuario
from app.seguridad import verificar_clave
from app.servicios import cuentas

router = APIRouter()


def _su_pagina(usuario: Usuario) -> str:
    """A dónde va alguien que acaba de entrar.

    Con la contraseña del alta todavía puesta no va a ninguna parte: primero
    `/clave`. Es el mismo corte que hace `usuario_actual`, escrito acá para que
    el ingreso no mande a una página que lo va a devolver.
    """
    if usuario.debe_cambiar_clave:
        return "/clave"
    return "/panel" if usuario.es_educador else "/hoy"


@router.get("/")
def raiz(usuario: Usuario | None = Depends(usuario_opcional)):
    if usuario is None:
        return redirigir("/ingresar")
    return redirigir(_su_pagina(usuario))


@router.get("/ingresar")
def form_ingreso(request: Request, usuario: Usuario | None = Depends(usuario_opcional)):
    if usuario is not None:
        return redirigir("/")
    return render(request, "ingresar.html")


@router.post("/ingresar")
def ingresar(
    request: Request,
    usuario: str = Form(...),
    clave: str = Form(...),
    sesion: Session = Depends(obtener_sesion),
):
    encontrado = sesion.scalar(
        select(Usuario).where(Usuario.usuario == cuentas.normalizar_login(usuario))
    )
    if (
        encontrado is None
        or not encontrado.activo
        or not verificar_clave(clave, encontrado.hash_clave)
    ):
        return render(
            request,
            "ingresar.html",
            error="Usuario o contraseña incorrectos.",
            usuario_ingresado=usuario,
        )

    request.session["usuario_id"] = encontrado.id
    return redirigir(_su_pagina(encontrado))


@router.get("/salir")
def salir(request: Request):
    request.session.clear()
    return redirigir("/ingresar")


# --- Mi contraseña -----------------------------------------------------------
#
# La cambia cada uno, joven o educador, y es la única forma de que una cuenta
# tenga una contraseña que no conozca nadie más. Cuelga de `usuario_de_sesion` y
# no de `usuario_actual` a propósito: es la única página que abre con la
# contraseña del alta puesta, porque es la que viene a sacarla.


@router.get("/clave")
def form_clave(
    request: Request,
    listo: str = "",
    usuario: Usuario = Depends(usuario_de_sesion),
):
    return render(
        request,
        "clave.html",
        usuario=usuario,
        obligatorio=usuario.debe_cambiar_clave,
        listo=bool(listo),
    )


@router.post("/clave")
def cambiar_clave(
    request: Request,
    actual: str = Form(...),
    nueva: str = Form(...),
    repetida: str = Form(...),
    usuario: Usuario = Depends(usuario_de_sesion),
    sesion: Session = Depends(obtener_sesion),
):
    try:
        cuentas.cambiar_clave(usuario, actual, nueva, repetida)
    except cuentas.DatoInvalido as error:
        # Se vuelve a mostrar el formulario vacío con el motivo. Vacío a
        # propósito: una contraseña no se devuelve escrita en el HTML.
        return render(
            request,
            "clave.html",
            usuario=usuario,
            obligatorio=usuario.debe_cambiar_clave,
            error=error.motivo,
        )

    sesion.commit()
    # Redirección y no una página servida sobre el POST: si alguien recarga, no
    # se reenvían las contraseñas. El cartel de «listo» sale del querystring.
    return redirigir("/clave?listo=1")
