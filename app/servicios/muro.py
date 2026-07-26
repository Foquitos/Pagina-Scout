"""El muro de la Unidad: lo que cada uno quiso mostrar de lo que hizo.

Un reto entregado lo ve quien lo entregó y el equipo de educadores, y nadie más.
Eso está bien para lo íntimo, pero desaprovecha lo que más empuja a un chico de
doce años a hacer algo: ver que otro lo hizo. La guía lo dice de otra manera
—«las y los jóvenes se reúnen, interactúan y aprenden a conocerse mutuamente
tomando parte en actividades (…) compartiendo ideas»— y llama a eso educación
entre pares.

Tres reglas, y las tres importan:

- **Se comparte porque uno quiso.** El interruptor arranca apagado y lo mueve
  quien escribió la entrega, en cualquier momento, para los dos lados.
- **Solo lo validado.** Al muro no llega algo que todavía se está mirando ni
  algo que se dio de baja. No es un tablón de anuncios, es lo que la Unidad hizo.
- **No hay número al lado.** Se ve qué hizo cada uno, no cuánto sumó: convertir
  el muro en un ranking de personas es exactamente lo que la guía evita al hacer
  que el puntaje sea siempre de la patrulla.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ESTADO_APROBADA, Asignacion, Entrega, Usuario


def publicaciones(sesion: Session, unidad_id: int, tope: int = 40) -> list[Entrega]:
    """Lo compartido en la Unidad, lo último primero."""
    return list(
        sesion.scalars(
            select(Entrega)
            .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
            .where(
                Asignacion.unidad_id == unidad_id,
                Entrega.compartida.is_(True),
                Entrega.estado == ESTADO_APROBADA,
            )
            .order_by(Entrega.enviada_en.desc())
            .limit(tope)
        )
    )


def puede_compartir(entrega: Entrega) -> bool:
    """Solo lo que ya está validado va al muro."""
    return entrega.estado == ESTADO_APROBADA


def alternar(entrega: Entrega, joven: Usuario) -> bool:
    """El autor prende o apaga el compartir. Devuelve cómo quedó."""
    if entrega.joven_id != joven.id:
        raise PermissionError("Esa entrega es de otra persona.")
    if not puede_compartir(entrega):
        entrega.compartida = False
        return False
    entrega.compartida = not entrega.compartida
    return entrega.compartida
