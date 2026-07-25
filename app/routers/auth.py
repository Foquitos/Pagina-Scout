"""Ingreso y salida."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, usuario_opcional
from app.models import Usuario
from app.seguridad import verificar_clave

router = APIRouter()


@router.get("/")
def raiz(usuario: Usuario | None = Depends(usuario_opcional)):
    if usuario is None:
        return redirigir("/ingresar")
    return redirigir("/panel" if usuario.es_educador else "/hoy")


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
        select(Usuario).where(Usuario.usuario == usuario.strip().lower())
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
    return redirigir("/panel" if encontrado.es_educador else "/hoy")


@router.get("/salir")
def salir(request: Request):
    request.session.clear()
    return redirigir("/ingresar")
