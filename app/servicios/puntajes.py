"""Puntajes.

El puntaje es siempre de la patrulla. No existe un ranking de personas ni una
vista que ordene jóvenes por puntos: la guía de la Rama dice explícitamente que
la progresión personal no es una carrera por insignias y que la evaluación es
personalizada, así que el único marcador público es el colectivo.

Lo que aporta cada joven se guarda (hace falta para acreditar el desafío en su
progresión) pero no se expone como número comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ESTADO_APROBADA,
    Asignacion,
    Entrega,
    Patrulla,
    Usuario,
)


@dataclass
class FilaTablero:
    patrulla: Patrulla
    puntos: int
    acciones: int
    integrantes: int
    racha: int


def _fechas_con_actividad(sesion: Session, patrulla_id: int) -> set[date]:
    consulta = (
        select(Asignacion.fecha)
        .join(Entrega, Entrega.asignacion_id == Asignacion.id)
        .where(Entrega.patrulla_id == patrulla_id, Entrega.estado == ESTADO_APROBADA)
        .distinct()
    )
    return set(sesion.scalars(consulta))


def racha_de_patrulla(sesion: Session, patrulla_id: int, hasta: date) -> int:
    """Días consecutivos con al menos una acción validada.

    Se cuenta hacia atrás desde hoy; si hoy todavía no hubo nada se arranca
    desde ayer, para no romper la racha a las 9 de la mañana.
    """
    fechas = _fechas_con_actividad(sesion, patrulla_id)
    if not fechas:
        return 0

    cursor = hasta if hasta in fechas else hasta - timedelta(days=1)
    racha = 0
    while cursor in fechas:
        racha += 1
        cursor -= timedelta(days=1)
    return racha


def tablero_de_unidad(sesion: Session, unidad_id: int, hasta: date) -> list[FilaTablero]:
    patrullas = list(
        sesion.scalars(
            select(Patrulla)
            .where(Patrulla.unidad_id == unidad_id, Patrulla.activa.is_(True))
            .order_by(Patrulla.nombre)
        )
    )

    totales = dict(
        sesion.execute(
            select(
                Entrega.patrulla_id,
                func.coalesce(func.sum(Entrega.puntaje_otorgado), 0),
            )
            .where(Entrega.estado == ESTADO_APROBADA)
            .group_by(Entrega.patrulla_id)
        ).all()
    )
    acciones = dict(
        sesion.execute(
            select(Entrega.patrulla_id, func.count(Entrega.id))
            .where(Entrega.estado == ESTADO_APROBADA)
            .group_by(Entrega.patrulla_id)
        ).all()
    )
    integrantes = dict(
        sesion.execute(
            select(Usuario.patrulla_id, func.count(Usuario.id))
            .where(Usuario.activo.is_(True))
            .group_by(Usuario.patrulla_id)
        ).all()
    )

    filas = [
        FilaTablero(
            patrulla=p,
            puntos=int(totales.get(p.id, 0)),
            acciones=int(acciones.get(p.id, 0)),
            integrantes=int(integrantes.get(p.id, 0)),
            racha=racha_de_patrulla(sesion, p.id, hasta),
        )
        for p in patrullas
    ]
    filas.sort(key=lambda f: (-f.puntos, f.patrulla.nombre))
    return filas
