"""API JSON.

Misma lógica que las páginas, en formato consumible: sirve para una app móvil
más adelante, y para probar el circuito sin abrir el navegador. Usa la misma
sesión por cookie que la web.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import usuario_actual
from app.models import Area, Competencia, Usuario
from app.servicios import puntajes, retos

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/yo")
def yo(usuario: Usuario = Depends(usuario_actual)):
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
        "etapa": usuario.etapa,
        "patrulla": usuario.patrulla.nombre if usuario.patrulla else None,
    }


@router.get("/areas")
def listar_areas(sesion: Session = Depends(obtener_sesion)):
    areas = sesion.scalars(select(Area).order_by(Area.id))
    return [
        {
            "codigo": a.codigo,
            "nombre": a.nombre,
            "color": a.color,
            "icono": a.icono,
            "descripcion": a.descripcion,
        }
        for a in areas
    ]


@router.get("/competencias")
def listar_competencias(
    area: str | None = None, sesion: Session = Depends(obtener_sesion)
):
    consulta = select(Competencia).order_by(Competencia.numero)
    if area:
        consulta = consulta.join(Area).where(Area.codigo == area)
    return [
        {
            "numero": c.numero,
            "area": c.area.codigo,
            "titulo": c.titulo,
            "desafios": [
                {"id": d.id, "orden": d.orden, "texto": d.texto, "tipo": d.tipo}
                for d in c.desafios
            ],
        }
        for c in sesion.scalars(consulta)
    ]


@router.get("/hoy")
def retos_de_hoy(
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    if usuario.unidad_id is None:
        return {"fecha": retos.hoy().isoformat(), "retos": []}

    fecha = retos.hoy()
    retos.asegurar_reto_del_dia(sesion, usuario.unidad_id, fecha)
    asignaciones = retos.asignaciones_del_dia(sesion, usuario, fecha)
    entregas = retos.entregas_por_asignacion(sesion, usuario, asignaciones)

    return {
        "fecha": fecha.isoformat(),
        "retos": [
            {
                "asignacion_id": a.id,
                "titulo": a.reto.titulo,
                "consigna": a.reto.consigna,
                "area": a.reto.area.nombre if a.reto.area else None,
                "puntaje": a.reto.puntaje,
                "pide_texto": a.reto.pide_texto,
                "pide_foto": a.reto.pide_foto,
                "alcance": a.alcance,
                "estado_entrega": entregas[a.id].estado if a.id in entregas else None,
            }
            for a in asignaciones
        ],
    }


@router.get("/tablero")
def tablero(
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    if usuario.unidad_id is None:
        return []
    filas = puntajes.tablero_de_unidad(sesion, usuario.unidad_id, retos.hoy())
    return [
        {
            "patrulla": f.patrulla.nombre,
            "color": f.patrulla.color,
            "puntos": f.puntos,
            "acciones": f.acciones,
            "integrantes": f.integrantes,
            "racha": f.racha,
        }
        for f in filas
    ]
