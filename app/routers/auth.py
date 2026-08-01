"""Ingreso, salida y la contraseña de la propia cuenta."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, usuario_de_sesion, usuario_opcional
from app.models import Usuario
from app.seguridad import anotar_fallo, espera_de_ingreso, olvidar_fallos, verificar_clave
from app.servicios import cuentas

router = APIRouter()


def _direccion(request: Request) -> str:
    """De qué dirección viene el pedido.

    Detrás del ingress de Container Apps `request.client` es el propio ingress y
    la de verdad viene en `X-Forwarded-For`. Se puede falsear —el que la manda es
    el cliente—, y por eso el freno por dirección es el secundario: el que de
    verdad protege es el de la cuenta, que no depende de nada que mande quien
    está del otro lado.
    """
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()[:64]
    return request.client.host if request.client else "desconocida"


def _cuanto_falta(segundos: int) -> str:
    if segundos >= 60:
        minutos = segundos // 60 + (1 if segundos % 60 else 0)
        return f"{minutos} minuto{'s' if minutos != 1 else ''}"
    return f"{segundos} segundo{'s' if segundos != 1 else ''}"


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
    """Ingreso, con un tope de intentos fallidos por cuenta y por dirección.

    Sin el tope, los nombres de usuario de una Unidad —que son adivinables— se
    pueden barrer probando contraseñas hasta que una entre. El detalle de por qué
    cinco y por cuánto tiempo está en `app/seguridad.py`.

    El mensaje del bloqueo no dice si la cuenta existe, igual que el de la
    contraseña equivocada: se responde lo mismo para un usuario que no existe
    que para uno que sí, o probar nombres sería una forma de averiguar quiénes
    están en la Unidad.
    """
    login = cuentas.normalizar_login(usuario)
    direccion = _direccion(request)

    falta = espera_de_ingreso(login, direccion)
    if falta:
        return render(
            request,
            "ingresar.html",
            error=(
                f"Demasiados intentos. Probá de nuevo en {_cuanto_falta(falta)}. "
                "Si no te acordás la contraseña, pedile a un educador que te la blanquee."
            ),
            usuario_ingresado=usuario,
        )

    encontrado = sesion.scalar(select(Usuario).where(Usuario.usuario == login))
    if (
        encontrado is None
        or not encontrado.activo
        or not verificar_clave(clave, encontrado.hash_clave)
    ):
        anotar_fallo(login, direccion)
        return render(
            request,
            "ingresar.html",
            error="Usuario o contraseña incorrectos.",
            usuario_ingresado=usuario,
        )

    olvidar_fallos(login, direccion)
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
