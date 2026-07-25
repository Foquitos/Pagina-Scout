"""Retos del día: qué ve cada joven al entrar y de dónde sale."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PUNTAJE_POR_DEFECTO, ZONA_HORARIA
from app.models import (
    ALCANCE_JOVEN,
    ALCANCE_PATRULLA,
    ALCANCE_UNIDAD,
    DESAFIO_ESPECIALIDAD,
    TIPO_CARTA,
    Asignacion,
    Competencia,
    Desafio,
    Entrega,
    Reto,
    Usuario,
)


def hoy() -> date:
    """El día de hoy en la zona horaria de la Unidad, no la del servidor."""
    return datetime.now(ZONA_HORARIA).date()


def asignaciones_del_dia(sesion: Session, joven: Usuario, fecha: date) -> list[Asignacion]:
    """Retos vigentes para un joven: los de su Unidad, su Patrulla y los suyos."""
    if joven.unidad_id is None:
        return []

    condiciones = [
        (Asignacion.alcance == ALCANCE_UNIDAD),
        (Asignacion.alcance == ALCANCE_JOVEN) & (Asignacion.joven_id == joven.id),
    ]
    if joven.patrulla_id is not None:
        condiciones.append(
            (Asignacion.alcance == ALCANCE_PATRULLA)
            & (Asignacion.patrulla_id == joven.patrulla_id)
        )

    from sqlalchemy import or_

    consulta = (
        select(Asignacion)
        .where(
            Asignacion.unidad_id == joven.unidad_id,
            Asignacion.fecha == fecha,
            or_(*condiciones),
        )
        .order_by(Asignacion.id)
    )
    return list(sesion.scalars(consulta))


def entregas_por_asignacion(
    sesion: Session, joven: Usuario, asignaciones: list[Asignacion]
) -> dict[int, Entrega]:
    if not asignaciones:
        return {}
    ids = [a.id for a in asignaciones]
    consulta = select(Entrega).where(
        Entrega.joven_id == joven.id, Entrega.asignacion_id.in_(ids)
    )
    return {e.asignacion_id: e for e in sesion.scalars(consulta)}


def _elegir_desafio_del_dia(sesion: Session, unidad_id: int, fecha: date) -> Desafio | None:
    """Elige un desafío de las cartas de forma estable para (unidad, fecha).

    Determinista a propósito: todos los de la Unidad ven el mismo reto ese día,
    y recargar la página no lo cambia.

    Quedan afuera los desafíos de especialidad y rol de patrulla: "desarrollo
    una especialidad de cocina" o "me desempeño como tesorero por un ciclo de
    programa" son recorridos de meses, no algo que se resuelva y se entregue hoy.
    """
    desafios = list(
        sesion.scalars(
            select(Desafio)
            .where(Desafio.tipo != DESAFIO_ESPECIALIDAD)
            .order_by(Desafio.id)
        )
    )
    if not desafios:
        return None
    semilla = f"{unidad_id}-{fecha.isoformat()}".encode()
    indice = int.from_bytes(hashlib.sha256(semilla).digest()[:8], "big") % len(desafios)
    return desafios[indice]


def asegurar_reto_del_dia(sesion: Session, unidad_id: int, fecha: date) -> Asignacion | None:
    """Si la Unidad no tiene ningún reto para hoy, propone uno de las cartas.

    Es una red de contención para que la página nunca aparezca vacía, no un
    reemplazo del educador: cualquier reto que él asigne desactiva este camino.
    """
    ya_hay = sesion.scalar(
        select(Asignacion.id).where(
            Asignacion.unidad_id == unidad_id, Asignacion.fecha == fecha
        )
    )
    if ya_hay is not None:
        return None

    desafio = _elegir_desafio_del_dia(sesion, unidad_id, fecha)
    if desafio is None:
        return None

    competencia = sesion.get(Competencia, desafio.competencia_id)
    reto = Reto(
        titulo=desafio.texto[:180],
        consigna=(
            f"Desafío de la carta {competencia.numero}: «{competencia.titulo}».\n\n"
            "Contá qué hiciste, cómo te salió y para qué sirve. "
            "Si podés, sumá una foto."
        ),
        tipo=TIPO_CARTA,
        desafio_id=desafio.id,
        area_id=competencia.area_id,
        puntaje=PUNTAJE_POR_DEFECTO,
        pide_texto=True,
        pide_foto=False,
        unidad_id=unidad_id,
    )
    sesion.add(reto)
    sesion.flush()

    asignacion = Asignacion(
        reto_id=reto.id,
        fecha=fecha,
        alcance=ALCANCE_UNIDAD,
        unidad_id=unidad_id,
        automatica=True,
    )
    sesion.add(asignacion)
    sesion.commit()
    return asignacion
