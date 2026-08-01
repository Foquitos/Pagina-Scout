"""El muro de la Unidad: lo que cada uno quiso mostrar de lo que hizo.

Un reto entregado lo ve quien lo entregó y el equipo de educadores, y nadie más.
Eso está bien para lo íntimo, pero desaprovecha lo que más empuja a un chico de
doce años a hacer algo: ver que otro lo hizo. La guía lo dice de otra manera
—«las y los jóvenes se reúnen, interactúan y aprenden a conocerse mutuamente
tomando parte en actividades (…) compartiendo ideas»— y llama a eso educación
entre pares.

Cuatro reglas, y las cuatro importan:

- **Se comparte porque uno quiso.** El interruptor arranca apagado y lo mueve
  quien escribió la entrega, en cualquier momento, para los dos lados.
- **Solo lo validado.** Al muro no llega algo que todavía se está mirando ni
  algo que se dio de baja. No es un tablón de anuncios, es lo que la Unidad hizo.
- **No hay número al lado.** Se ve qué hizo cada uno, no cuánto sumó: convertir
  el muro en un ranking de personas es exactamente lo que la guía evita al hacer
  que el puntaje sea siempre de la patrulla.
- **El equipo puede bajar algo, y cualquiera puede pedirlo.** Se publica en el
  momento, sin que un adulto lo mire antes; el precio de esa inmediatez es que
  sacar una foto del muro tenga que ser inmediato también. Eso vive en
  `servicios/moderacion.py`, que es de dónde sale `oculta_en`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ESTADO_APROBADA, Asignacion, Entrega, Usuario


def publicaciones(sesion: Session, unidad_id: int, tope: int = 40) -> list[Entrega]:
    """Lo compartido en la Unidad, lo último publicado primero.

    Ordena por cuándo se compartió y no por cuándo se entregó: compartir algo de
    marzo en noviembre lo pone arriba, que es donde tiene que estar, porque para
    la Unidad la novedad es de noviembre.
    """
    return list(
        sesion.scalars(
            select(Entrega)
            .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
            .where(
                Asignacion.unidad_id == unidad_id,
                Entrega.compartida.is_(True),
                Entrega.estado == ESTADO_APROBADA,
                # Lo que el equipo bajó no está en el muro para nadie, tampoco
                # para su autor: si lo viera solo él, creería que sigue puesto.
                Entrega.oculta_en.is_(None),
            )
            .order_by(func.coalesce(Entrega.compartida_en, Entrega.enviada_en).desc())
            .limit(tope)
        )
    )


def puede_compartir(entrega: Entrega) -> bool:
    """Solo lo que ya está validado va al muro, y nada que el equipo haya bajado."""
    return entrega.estado == ESTADO_APROBADA and not entrega.oculta


def alternar(entrega: Entrega, joven: Usuario) -> bool:
    """El autor prende o apaga el compartir. Devuelve cómo quedó."""
    if entrega.joven_id != joven.id:
        raise PermissionError("Esa entrega es de otra persona.")
    if not puede_compartir(entrega):
        entrega.compartida = False
        return False
    entrega.compartida = not entrega.compartida
    # La fecha se pisa cada vez que se prende: sacar algo del muro y volver a
    # ponerlo lo publica de nuevo, y el equipo tiene que volver a verlo arriba.
    entrega.compartida_en = datetime.now(timezone.utc) if entrega.compartida else None
    return entrega.compartida
