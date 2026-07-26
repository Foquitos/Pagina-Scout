"""Puntajes.

El puntaje es siempre de la patrulla. No existe un ranking de personas ni una
vista que ordene jóvenes por puntos: la guía de la Rama dice explícitamente que
la progresión personal no es una carrera por insignias y que la evaluación es
personalizada, así que el único marcador público es el colectivo.

Lo que aporta cada joven se guarda (hace falta para acreditar el desafío en su
progresión) pero no se expone como número comparable.

**El tablero se ordena por promedio, no por total.** El capítulo 4 avisa que las
patrullas son desparejas y que eso está bien —«es frecuente que en una Unidad
Scout haya patrullas desparejas en número (…) Esta heterogeneidad nos muestra
que estamos en buen camino»— y hasta pide no repartir a los que llegan «con la
intención de que todas las patrullas queden con un número similar». Si el
marcador sumara nomás, la aplicación estaría premiando exactamente lo que la
guía dice que no hay que hacer: una patrulla de ocho le gana siempre a una de
cuatro sin que nadie se haya esforzado más.

Así que la cifra grande es **puntos por integrante**. El total sigue estando a la
vista, porque es lo que la patrulla siente que hizo; lo que no hace es decidir
quién va arriba.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ESTADO_APROBADA,
    ROL_JOVEN,
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

    @property
    def promedio(self) -> float:
        """Puntos por integrante: la cifra que ordena el tablero.

        Una patrulla sin integrantes activos da 0 y no una división por cero;
        tampoco tendría a quién premiarle nada.
        """
        if not self.integrantes:
            return 0.0
        return self.puntos / self.integrantes

    @property
    def promedio_texto(self) -> str:
        """Sin decimal cuando es redondo: «30» se lee mejor que «30.0»."""
        valor = round(self.promedio, 1)
        return str(int(valor)) if valor == int(valor) else f"{valor:.1f}"


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
    # Solo jóvenes: un educador que figure en una patrulla no la agranda para
    # el promedio, porque no entrega retos.
    integrantes = dict(
        sesion.execute(
            select(Usuario.patrulla_id, func.count(Usuario.id))
            .where(Usuario.activo.is_(True), Usuario.rol == ROL_JOVEN)
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
    # Por promedio. El total desempata, y el nombre desempata al total: hace
    # falta un orden estable para que la lista no salte entre recargas.
    filas.sort(key=lambda f: (-f.promedio, -f.puntos, f.patrulla.nombre))
    return filas
