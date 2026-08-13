"""Especialidades: lo que un joven pide y lo que el equipo prepara (cap. 9).

Las dos mitades viven acá y no repartidas entre `joven.py` y `educador.py`,
porque son la misma URL: `/especialidades` le muestra a cada uno lo suyo —al
joven, lo que pidió y en qué anda; al equipo, los pedidos que esperan respuesta y
lo que hay en curso—. Partirlo en dos routers haría que uno le tapara las rutas
al otro, que es exactamente lo que pasó la primera vez.

El reparto de atribuciones sigue al método:

- **Pedir**: el joven, la que quiera y sin pedir permiso. «El único requisito es
  que lo desee.» Pedirla es el aviso: aparece en el panel del equipo.
- **Preparar**: el equipo. Conocer el tema, conseguir a la persona experta y
  escribir qué se espera en cada fase, para *esa* persona.
- **Escribir las fases**: el joven, que es quien las está viviendo.
- **Dar por concluida**: el equipo. La insignia «constituye un testimonio
  permanente de la actitud de servicio», y eso lo atestigua una persona.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import (
    quiere_json,
    redirigir,
    render,
    solo_educador,
    solo_joven,
    usuario_actual,
)
from app.models import FASES_ESPECIALIDAD, FASES_ESPECIALIDAD_NOMBRE, Especialidad, Usuario
from app.servicios import especialidades

router = APIRouter()


def _unidad_de(usuario: Usuario) -> int:
    if usuario.unidad_id is None:
        raise HTTPException(400, "Tu usuario no está asociado a ninguna Unidad.")
    return usuario.unidad_id


def _mia(sesion: Session, especialidad_id: int, joven: Usuario) -> Especialidad:
    especialidad = sesion.get(Especialidad, especialidad_id)
    if especialidad is None or especialidad.joven_id != joven.id:
        raise HTTPException(404, "Esa especialidad no es tuya.")
    return especialidad


def _de_mi_unidad(sesion: Session, especialidad_id: int, educador: Usuario) -> Especialidad:
    especialidad = sesion.get(Especialidad, especialidad_id)
    if especialidad is None:
        raise HTTPException(404, "Esa especialidad no existe.")
    joven = sesion.get(Usuario, especialidad.joven_id)
    if joven is None or joven.unidad_id != _unidad_de(educador):
        raise HTTPException(404, "Esa especialidad no es de tu Unidad.")
    return especialidad


@router.get("/especialidades")
def ver(
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """La misma dirección, dos páginas: la de quien las hace y la de quien las prepara."""
    if usuario.es_educador:
        unidad_id = _unidad_de(usuario)
        return render(
            request,
            "educador/especialidades.html",
            usuario=usuario,
            en_curso=especialidades.en_curso(sesion, unidad_id),
            sugerencias=especialidades.sugerencias(sesion),
            fases=FASES_ESPECIALIDAD,
            fases_nombre=FASES_ESPECIALIDAD_NOMBRE,
        )

    # Al joven no se le ofrecen sugerencias: el tema lo elige y lo nombra él. Las
    # de las cartas quedan del lado del equipo, como referencia para preparar.
    return render(
        request,
        "joven/especialidades.html",
        usuario=usuario,
        especialidades=especialidades.de(sesion, usuario),
        fases=FASES_ESPECIALIDAD,
        fases_nombre=FASES_ESPECIALIDAD_NOMBRE,
    )


# --- Lo que hace el joven -----------------------------------------------------


@router.post("/especialidades")
def pedir(
    nombre: str = Form(...),
    motivo: str = Form(""),
    icono: str = Form(""),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """Pedir la especialidad que uno quiera. El campo es libre a propósito.

    Un menú cerrado convertiría en «no se puede» todo lo que a los adultos no se
    les ocurrió. Pedirla es además el aviso: aparece en el panel del equipo.
    """
    try:
        pedida = especialidades.pedir(sesion, usuario, nombre, motivo, icono)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    sesion.commit()
    return redirigir(f"/especialidades#especialidad-{pedida.id}")


@router.post("/especialidades/{especialidad_id}")
def escribir(
    especialidad_id: int,
    request: Request,
    fase: str = Form(...),
    texto: str = Form(""),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    especialidad = _mia(sesion, especialidad_id, usuario)
    try:
        especialidades.escribir(especialidad, fase, texto)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    sesion.commit()

    if quiere_json(request):
        return {"fase": especialidad.fase}
    return redirigir(f"/especialidades#especialidad-{especialidad.id}")


@router.post("/especialidades/{especialidad_id}/borrar")
def dejarla(
    especialidad_id: int,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """Dejar una a medio camino no es un fracaso: es información.

    Una lograda no se borra: eso ya es parte del recorrido de la persona.
    """
    especialidad = _mia(sesion, especialidad_id, usuario)
    if especialidad.lograda:
        raise HTTPException(400, "Una especialidad lograda queda: es tuya.")

    sesion.delete(especialidad)
    sesion.commit()
    return redirigir("/especialidades")


# --- Lo que hace el equipo ----------------------------------------------------


@router.post("/especialidades/{especialidad_id}/preparar")
def preparar(
    especialidad_id: int,
    experto: str = Form(""),
    pide_exploracion: str = Form(""),
    pide_taller: str = Form(""),
    pide_desafio: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """La respuesta del equipo a un pedido: el recorrido de esa especialidad.

    Se puede volver a preparar cuantas veces haga falta: ajustar lo pedido a la
    realidad de cada joven es exactamente lo que la guía pide.
    """
    especialidad = _de_mi_unidad(sesion, especialidad_id, usuario)
    especialidades.preparar(
        especialidad, usuario, experto, pide_exploracion, pide_taller, pide_desafio
    )
    sesion.commit()
    return redirigir("/especialidades#especialidad-" + str(especialidad.id))


@router.post("/especialidades/{especialidad_id}/entregar")
def entregar(
    especialidad_id: int,
    reabrir: bool = Form(False),
    nota: str = Form(""),
    volver: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Dar por concluida una especialidad. La cierra un educador, siempre."""
    especialidad = _de_mi_unidad(sesion, especialidad_id, usuario)
    if reabrir:
        especialidades.reabrir(especialidad)
    else:
        especialidades.lograr(especialidad, usuario, nota)
    sesion.commit()

    if volver == "listado":
        return redirigir("/especialidades")
    return redirigir(f"/progresion/{especialidad.joven_id}#especialidades")
