"""Ideas: qué quiere hacer la Unidad (cap. 8).

Acá las y los jóvenes proponen. La Asamblea que decide **no está en la
aplicación**: se junta en persona, que es donde se aprende a discutir y a
bancarse perder una votación. Lo que la pantalla hace es juntar las propuestas
para que lleguen enteras a esa reunión y anotar después lo que ahí se decidió.

Quién puede qué:

- **Proponer**: cualquiera, incluido el equipo de educadores, a quienes la guía
  les pide expresamente proponer «para introducir nuevas temáticas y actividades
  novedosas (…) Esta es una responsabilidad educativa que no debemos delegar».
- **Apoyar** («me sumo»): solo las y los jóvenes. No decide nada: es un dato
  para llevar a la reunión.
- **Mover una idea** —se puede hacer, la eligieron, se guarda para después— y
  **agendarla**: el equipo, que es quien coordina el Consejo de Unidad.
- **Borrar**: el equipo, o quien la escribió mientras nadie la haya mirado.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, solo_educador, usuario_actual
from app.models import (
    CLASES_ACTIVIDAD,
    CLASES_ACTIVIDAD_NOMBRE,
    IDEA_ELEGIDA,
    IDEAS_ESTADO,
    IDEAS_ESTADO_NOMBRE,
    Idea,
    Usuario,
)
from app.servicios import agenda, participacion, retos

router = APIRouter()


def _idea_de_la_unidad(sesion: Session, idea_id: int, usuario: Usuario) -> Idea:
    idea = sesion.get(Idea, idea_id)
    if idea is None or idea.unidad_id != usuario.unidad_id:
        raise HTTPException(404, "Esa idea no existe.")
    return idea


def _fecha(texto: str, por_defecto: date) -> date:
    try:
        return date.fromisoformat(texto.strip())
    except (AttributeError, ValueError):
        return por_defecto


@router.get("/ideas")
def buzon(
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Todo lo que alguien propuso, y en qué anda cada cosa."""
    if usuario.unidad_id is None:
        return render(request, "ideas.html", usuario=usuario, ideas=[])

    ideas = participacion.ideas_de_unidad(sesion, usuario.unidad_id)
    return render(
        request,
        "ideas.html",
        usuario=usuario,
        ideas=ideas,
        apoyos=participacion.apoyos_de(sesion, ideas),
        mis_apoyos=(
            participacion.apoyos_propios(sesion, usuario, ideas)
            if not usuario.es_educador
            else set()
        ),
        borrables={i.id for i in ideas if participacion.puede_borrar(usuario, i)},
        clases=CLASES_ACTIVIDAD,
        clases_nombre=CLASES_ACTIVIDAD_NOMBRE,
        estados=IDEAS_ESTADO,
        estados_nombre=IDEAS_ESTADO_NOMBRE,
        hoy=retos.hoy(),
    )


@router.post("/ideas")
def proponer(
    titulo: str = Form(...),
    texto: str = Form(""),
    hace_falta: str = Form(""),
    clase: str = Form("actividad"),
    ambito: str = Form("unidad"),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    try:
        participacion.proponer(sesion, usuario, titulo, texto, hace_falta, clase, ambito)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    sesion.commit()
    return redirigir("/ideas")


@router.post("/ideas/{idea_id}/apoyo")
def apoyar(
    idea_id: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """«Me sumo». No es un voto: es saber cuántos la quieren antes de discutirla."""
    if usuario.es_educador:
        raise HTTPException(403, "Apoyar una idea es de las y los jóvenes.")
    idea = _idea_de_la_unidad(sesion, idea_id, usuario)
    participacion.alternar_apoyo(sesion, idea, usuario)
    sesion.commit()
    return redirigir(f"/ideas#idea-{idea.id}")


@router.post("/ideas/{idea_id}/estado")
def mover_idea(
    idea_id: int,
    estado: str = Form(...),
    respuesta: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """El equipo dice en qué anda una idea.

    «Elegida» se marca **después** de la Asamblea, que pasó en persona: la
    aplicación no la elige, la anota.
    """
    idea = _idea_de_la_unidad(sesion, idea_id, usuario)
    try:
        participacion.mover(idea, estado, respuesta)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    sesion.commit()
    return redirigir(f"/ideas#idea-{idea.id}")


@router.post("/ideas/{idea_id}/agendar")
def agendar_idea(
    idea_id: int,
    fecha: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Una idea se convierte en una fecha del calendario.

    Que un chico vea su propuesta convertida en una fecha es la mitad del valor
    educativo de todo esto. Queda además marcada como elegida: llegó hasta acá.
    """
    idea = _idea_de_la_unidad(sesion, idea_id, usuario)
    agenda.agendar(
        sesion,
        unidad_id=idea.unidad_id,
        titulo=idea.titulo,
        fecha=_fecha(fecha, retos.hoy()),
        clase=idea.clase,
        creada_por=usuario,
        detalle=idea.texto,
        patrulla_id=idea.patrulla_id if idea.ambito != "unidad" else None,
        idea_id=idea.id,
    )
    participacion.mover(idea, IDEA_ELEGIDA)
    sesion.commit()
    return redirigir("/calendario")


@router.post("/ideas/{idea_id}/borrar")
def borrar_idea(
    idea_id: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """La borra el equipo, o quien la escribió mientras nadie la haya mirado."""
    idea = _idea_de_la_unidad(sesion, idea_id, usuario)
    if not participacion.puede_borrar(usuario, idea):
        raise HTTPException(
            403,
            "Esa idea ya la miró el equipo: pedile a un educador que la saque.",
        )
    sesion.delete(idea)
    sesion.commit()
    return redirigir("/ideas")
