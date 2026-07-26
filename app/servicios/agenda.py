"""El calendario del Ciclo de Programa (cap. 8, fase 3).

«Tanto las actividades, descubiertas y proyectos elegidos por las y los jóvenes
como las actividades fijas deben ser organizadas en un calendario». Eso es esta
tabla: lo que viene, de quién es, y quién estuvo.

Hasta acá un joven abría la aplicación y veía el día de hoy. Saber que en tres
semanas hay campamento es la mitad de las ganas de ir.

Ojo con la diferencia entre esto y las asignaciones de retos: un reto es una
propuesta de acción individual que se entrega y se puntúa; una actividad del
calendario es algo que la Unidad **hace junta** y que no se entrega ni se puntúa
nunca. Son dos cosas distintas a propósito.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    CLASE_DESCUBIERTA,
    CLASE_PROYECTO,
    CLASES_ACTIVIDAD,
    Actividad,
    ParticipacionActividad,
    Usuario,
)


def _visibles_para(joven: Usuario):
    """Las de la Unidad y las de su patrulla. Las de otra patrulla, no.

    Igual que el Libro de Oro: lo de una patrulla es de esa patrulla.
    """
    condiciones = [Actividad.patrulla_id.is_(None)]
    if joven.patrulla_id is not None:
        condiciones.append(Actividad.patrulla_id == joven.patrulla_id)
    return or_(*condiciones)


def proximas(
    sesion: Session, usuario: Usuario, desde: date, tope: int = 6
) -> list[Actividad]:
    """Lo que viene. Un campamento sigue apareciendo mientras esté transcurriendo."""
    if usuario.unidad_id is None:
        return []
    consulta = select(Actividad).where(
        Actividad.unidad_id == usuario.unidad_id,
        or_(
            Actividad.fecha >= desde,
            (Actividad.hasta.is_not(None)) & (Actividad.hasta >= desde),
        ),
    )
    if not usuario.es_educador:
        consulta = consulta.where(_visibles_para(usuario))
    return list(sesion.scalars(consulta.order_by(Actividad.fecha).limit(tope)))


def pasadas(
    sesion: Session, usuario: Usuario, antes_de: date, tope: int = 40
) -> list[Actividad]:
    if usuario.unidad_id is None:
        return []
    consulta = select(Actividad).where(
        Actividad.unidad_id == usuario.unidad_id,
        Actividad.fecha < antes_de,
    )
    if not usuario.es_educador:
        consulta = consulta.where(_visibles_para(usuario))
    return list(
        sesion.scalars(consulta.order_by(Actividad.fecha.desc()).limit(tope))
    )


def participaciones_de(sesion: Session, joven: Usuario) -> set[int]:
    """En qué actividades marcó «estuve»."""
    return set(
        sesion.scalars(
            select(ParticipacionActividad.actividad_id).where(
                ParticipacionActividad.joven_id == joven.id
            )
        )
    )


def alternar_estuve(sesion: Session, actividad: Actividad, joven: Usuario) -> bool:
    existente = sesion.scalar(
        select(ParticipacionActividad).where(
            ParticipacionActividad.actividad_id == actividad.id,
            ParticipacionActividad.joven_id == joven.id,
        )
    )
    if existente is not None:
        sesion.delete(existente)
        return False
    sesion.add(ParticipacionActividad(actividad_id=actividad.id, joven_id=joven.id))
    return True


@dataclass
class LoQueHizo:
    """En qué participó, de lo que los requisitos de etapa miran (cap. 9)."""

    descubiertas: int = 0
    proyectos_unidad: int = 0
    proyectos_patrulla: int = 0

    @property
    def proyectos(self) -> int:
        return self.proyectos_unidad + self.proyectos_patrulla


def lo_que_hizo(sesion: Session, joven: Usuario) -> LoQueHizo:
    """Cuenta descubiertas y proyectos en los que dijo haber estado.

    Sale de lo que marcó el propio joven y no de una lista de asistencia que
    lleva un adulto, que es coherente con que la evaluación de la progresión sea
    suya (cap. 9).
    """
    filas = sesion.execute(
        select(Actividad.clase, Actividad.patrulla_id)
        .join(
            ParticipacionActividad,
            ParticipacionActividad.actividad_id == Actividad.id,
        )
        .where(ParticipacionActividad.joven_id == joven.id)
    )
    hizo = LoQueHizo()
    for clase, patrulla_id in filas:
        if clase == CLASE_DESCUBIERTA:
            hizo.descubiertas += 1
        elif clase == CLASE_PROYECTO:
            if patrulla_id is None:
                hizo.proyectos_unidad += 1
            else:
                hizo.proyectos_patrulla += 1
    return hizo


def agendar(
    sesion: Session,
    unidad_id: int,
    titulo: str,
    fecha: date,
    clase: str,
    creada_por: Usuario,
    detalle: str = "",
    lugar: str = "",
    hasta: date | None = None,
    patrulla_id: int | None = None,
    idea_id: int | None = None,
) -> Actividad:
    if not titulo.strip():
        raise ValueError("La actividad necesita un título.")
    if clase not in CLASES_ACTIVIDAD:
        clase = CLASES_ACTIVIDAD[0]
    # Un «hasta» anterior al día de inicio no es un rango, es un error de tipeo.
    if hasta is not None and hasta <= fecha:
        hasta = None

    actividad = Actividad(
        unidad_id=unidad_id,
        patrulla_id=patrulla_id,
        titulo=titulo.strip()[:200],
        detalle=detalle.strip(),
        lugar=lugar.strip()[:160],
        fecha=fecha,
        hasta=hasta,
        clase=clase,
        idea_id=idea_id,
        creada_por_id=creada_por.id,
    )
    sesion.add(actividad)
    sesion.flush()
    return actividad
