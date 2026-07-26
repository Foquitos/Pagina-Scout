"""El calendario del ciclo: qué viene y quién estuvo (cap. 8, fase 3).

Lo arma el equipo de educadores porque la fase de organización es del Consejo de
Unidad, que ellos coordinan. Lo que hacen las y los jóvenes acá es lo que
importa para su progresión: marcar en qué estuvieron.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, solo_educador, usuario_actual
from app.models import (
    CLASES_ACTIVIDAD,
    CLASES_ACTIVIDAD_NOMBRE,
    Actividad,
    Patrulla,
    Usuario,
)
from app.servicios import agenda, retos

router = APIRouter()


def _fecha(texto: str, por_defecto: date | None = None) -> date | None:
    try:
        return date.fromisoformat(texto.strip())
    except (AttributeError, ValueError):
        return por_defecto


def _actividad_visible(sesion: Session, actividad_id: int, usuario: Usuario) -> Actividad:
    actividad = sesion.get(Actividad, actividad_id)
    if actividad is None or actividad.unidad_id != usuario.unidad_id:
        raise HTTPException(404, "Esa actividad no existe.")
    if (
        not usuario.es_educador
        and actividad.patrulla_id is not None
        and actividad.patrulla_id != usuario.patrulla_id
    ):
        raise HTTPException(404, "Esa actividad no existe.")
    return actividad


@router.get("/calendario")
def calendario(
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Lo que viene arriba y lo que pasó abajo, que es donde se marca «estuve»."""
    hoy = retos.hoy()
    if usuario.unidad_id is None:
        return render(
            request, "calendario.html", usuario=usuario, proximas=[], pasadas=[], hoy=hoy
        )

    patrullas = list(
        sesion.scalars(
            select(Patrulla)
            .where(Patrulla.unidad_id == usuario.unidad_id, Patrulla.activa.is_(True))
            .order_by(Patrulla.nombre)
        )
    )
    return render(
        request,
        "calendario.html",
        usuario=usuario,
        hoy=hoy,
        proximas=agenda.proximas(sesion, usuario, hoy, tope=30),
        pasadas=agenda.pasadas(sesion, usuario, hoy),
        estuve=(
            agenda.participaciones_de(sesion, usuario) if not usuario.es_educador else set()
        ),
        clases=CLASES_ACTIVIDAD,
        clases_nombre=CLASES_ACTIVIDAD_NOMBRE,
        patrullas=patrullas,
    )


@router.post("/calendario")
def agendar(
    titulo: str = Form(...),
    fecha: str = Form(""),
    hasta: str = Form(""),
    clase: str = Form("actividad"),
    detalle: str = Form(""),
    lugar: str = Form(""),
    patrulla_id: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    if usuario.unidad_id is None:
        raise HTTPException(400, "No tenés una Unidad asignada.")

    de_patrulla = None
    if patrulla_id.strip().isdigit():
        candidata = sesion.get(Patrulla, int(patrulla_id))
        if candidata is not None and candidata.unidad_id == usuario.unidad_id:
            de_patrulla = candidata.id

    try:
        agenda.agendar(
            sesion,
            unidad_id=usuario.unidad_id,
            titulo=titulo,
            fecha=_fecha(fecha, retos.hoy()) or retos.hoy(),
            clase=clase,
            creada_por=usuario,
            detalle=detalle,
            lugar=lugar,
            hasta=_fecha(hasta),
            patrulla_id=de_patrulla,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    sesion.commit()
    return redirigir("/calendario")


@router.post("/calendario/{actividad_id}/estuve")
def estuve(
    actividad_id: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """«Estuve». Lo marca el joven, y es lo que cuenta para su etapa.

    No lo puede marcar un educador por otro: la guía pone la evaluación de la
    progresión del lado del joven, y esto es parte de eso.
    """
    if usuario.es_educador:
        raise HTTPException(403, "Esto lo marca cada joven por sí mismo.")
    actividad = _actividad_visible(sesion, actividad_id, usuario)
    agenda.alternar_estuve(sesion, actividad, usuario)
    sesion.commit()
    return redirigir(f"/calendario#actividad-{actividad.id}")


@router.post("/calendario/{actividad_id}/borrar")
def borrar(
    actividad_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Saca una fecha del calendario, con lo que se marcó en ella."""
    actividad = _actividad_visible(sesion, actividad_id, usuario)
    sesion.delete(actividad)
    sesion.commit()
    return redirigir("/calendario")
