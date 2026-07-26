"""La vida interna de la patrulla: cargos, Consejo y acuerdos (cap. 4).

Esto es la mitad del Método Scout que la aplicación no tenía. Hasta acá sabía
acompañar la progresión de cada joven —sus cartas, sus desafíos, su etapa— pero
no que la patrulla se gobierna sola: elige a su Guía, reparte responsabilidades,
se reúne a decidir y se hace cargo de lo que decidió.

La guía es explícita en que esto no lo administra un adulto. El Consejo de
Patrulla evalúa el desempeño de los cargos, no el educador; los períodos no
tienen duración fija; y quien escribe el acta es alguien de la patrulla.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ROL_JOVEN,
    Acuerdo,
    Cargo,
    ConsejoPatrulla,
    PeriodoCargo,
    PresenciaConsejo,
    Usuario,
)


# --- Cargos -------------------------------------------------------------------


def catalogo(sesion: Session, unidad_id: int, incluir_bajas: bool = False) -> list[Cargo]:
    consulta = select(Cargo).where(Cargo.unidad_id == unidad_id)
    if not incluir_bajas:
        consulta = consulta.where(Cargo.activo.is_(True))
    return list(sesion.scalars(consulta.order_by(Cargo.orden, Cargo.nombre)))


def periodos_de(sesion: Session, joven: Usuario) -> list[PeriodoCargo]:
    """Todo lo que esta persona desempeñó, lo abierto primero."""
    return list(
        sesion.scalars(
            select(PeriodoCargo)
            .where(PeriodoCargo.joven_id == joven.id)
            .order_by(PeriodoCargo.desde.desc(), PeriodoCargo.id.desc())
        )
    )


def periodos_abiertos(sesion: Session, patrulla_id: int) -> list[PeriodoCargo]:
    """Quién tiene qué cargo puesto hoy en esa patrulla."""
    return list(
        sesion.scalars(
            select(PeriodoCargo)
            .where(
                PeriodoCargo.patrulla_id == patrulla_id,
                PeriodoCargo.hasta.is_(None),
            )
            .order_by(PeriodoCargo.desde)
        )
    )


def cargos_por_joven(sesion: Session, patrulla_id: int) -> dict[int, list[PeriodoCargo]]:
    """Los cargos abiertos indexados por persona, para pintar la lista de una."""
    porta: dict[int, list[PeriodoCargo]] = {}
    for periodo in periodos_abiertos(sesion, patrulla_id):
        porta.setdefault(periodo.joven_id, []).append(periodo)
    return porta


def cumplidos_distintos(sesion: Session, joven: Usuario) -> int:
    """Cuántos cargos **distintos** cumplió a lo largo de su paso por la Rama.

    Distintos y no cuántas veces: la etapa Senda pide «un rol de patrulla
    diferente al que ha desempeñado en etapas anteriores», así que repetir el
    mismo cargo tres ciclos no es lo que la guía cuenta.
    """
    return (
        sesion.scalar(
            select(func.count(func.distinct(PeriodoCargo.cargo_id))).where(
                PeriodoCargo.joven_id == joven.id,
                PeriodoCargo.cumplido.is_(True),
            )
        )
        or 0
    )


def asumir(
    sesion: Session,
    cargo: Cargo,
    joven: Usuario,
    desde: date,
) -> PeriodoCargo:
    """Alguien toma un cargo. Si ya tenía ese mismo abierto, no se duplica."""
    abierto = sesion.scalar(
        select(PeriodoCargo).where(
            PeriodoCargo.joven_id == joven.id,
            PeriodoCargo.cargo_id == cargo.id,
            PeriodoCargo.hasta.is_(None),
        )
    )
    if abierto is not None:
        return abierto

    periodo = PeriodoCargo(
        cargo_id=cargo.id,
        joven_id=joven.id,
        patrulla_id=joven.patrulla_id,
        desde=desde,
    )
    sesion.add(periodo)
    sesion.flush()
    return periodo


def cerrar(periodo: PeriodoCargo, hasta: date, cumplido: bool, nota: str = "") -> None:
    """El Consejo cierra un período y dice cómo le fue.

    `cumplido` es la evaluación de la patrulla, no del educador: la guía pide
    «que al interior de la Patrulla existan evaluaciones regulares del desempeño
    de los cargos». Un período cerrado sin cumplir no es un castigo, es
    información: el chico puede volver a tomarlo o tomar otro.
    """
    periodo.hasta = hasta
    periodo.cumplido = cumplido
    periodo.nota = nota.strip()


# --- Consejo de Patrulla ------------------------------------------------------


def consejos_de(sesion: Session, patrulla_id: int, tope: int = 20) -> list[ConsejoPatrulla]:
    return list(
        sesion.scalars(
            select(ConsejoPatrulla)
            .where(ConsejoPatrulla.patrulla_id == patrulla_id)
            .order_by(ConsejoPatrulla.fecha.desc(), ConsejoPatrulla.id.desc())
            .limit(tope)
        )
    )


def anotar_consejo(
    sesion: Session,
    patrulla_id: int,
    fecha: date,
    temas: str,
    escribio: Usuario,
    presentes: list[int],
) -> ConsejoPatrulla:
    consejo = ConsejoPatrulla(
        patrulla_id=patrulla_id,
        fecha=fecha,
        temas=temas.strip(),
        escribio_id=escribio.id,
    )
    sesion.add(consejo)
    sesion.flush()

    integrantes = {
        j.id
        for j in sesion.scalars(
            select(Usuario).where(
                Usuario.patrulla_id == patrulla_id,
                Usuario.rol == ROL_JOVEN,
                Usuario.activo.is_(True),
            )
        )
    }
    for joven_id in dict.fromkeys(presentes):  # sin repetidos y en orden
        if joven_id in integrantes:
            sesion.add(PresenciaConsejo(consejo_id=consejo.id, joven_id=joven_id))
    return consejo


# --- Acuerdos -----------------------------------------------------------------


def acuerdos_de(
    sesion: Session, patrulla_id: int, solo_pendientes: bool = False
) -> list[Acuerdo]:
    """Los acuerdos de la patrulla. Los que tienen fecha, primero por fecha.

    Un acuerdo sin `para_cuando` no es menos importante, pero no compite con los
    que tienen día: van después.
    """
    consulta = select(Acuerdo).where(Acuerdo.patrulla_id == patrulla_id)
    if solo_pendientes:
        consulta = consulta.where(Acuerdo.cumplido.is_(False))
    return list(
        sesion.scalars(
            consulta.order_by(
                Acuerdo.cumplido,
                Acuerdo.para_cuando.is_(None),
                Acuerdo.para_cuando,
                Acuerdo.id.desc(),
            )
        )
    )


def acuerdos_a_cargo_de(sesion: Session, joven: Usuario) -> list[Acuerdo]:
    """Lo que esta persona se comprometió a hacer y todavía no dio por hecho.

    Esto es lo que va a `/hoy`: un acuerdo que se queda escrito en un acta es
    una anotación; uno que te espera en la pantalla de entrada es un compromiso.
    """
    return list(
        sesion.scalars(
            select(Acuerdo)
            .where(
                Acuerdo.responsable_id == joven.id,
                Acuerdo.cumplido.is_(False),
            )
            .order_by(Acuerdo.para_cuando.is_(None), Acuerdo.para_cuando, Acuerdo.id)
        )
    )


@dataclass
class ResumenPatrulla:
    """Lo que se muestra arriba de todo en la página de la patrulla."""

    integrantes: int = 0
    con_cargo: int = 0
    acuerdos_pendientes: int = 0
    ultimo_consejo: date | None = None
    sin_cargo: list[Usuario] = field(default_factory=list)

    @property
    def hay_quien_no_tiene_cargo(self) -> bool:
        return bool(self.sin_cargo)


def resumen(sesion: Session, patrulla_id: int, integrantes: list[Usuario]) -> ResumenPatrulla:
    porta = cargos_por_joven(sesion, patrulla_id)
    ultimo = sesion.scalar(
        select(func.max(ConsejoPatrulla.fecha)).where(
            ConsejoPatrulla.patrulla_id == patrulla_id
        )
    )
    pendientes = (
        sesion.scalar(
            select(func.count(Acuerdo.id)).where(
                Acuerdo.patrulla_id == patrulla_id,
                Acuerdo.cumplido.is_(False),
            )
        )
        or 0
    )
    return ResumenPatrulla(
        integrantes=len(integrantes),
        con_cargo=sum(1 for j in integrantes if porta.get(j.id)),
        acuerdos_pendientes=pendientes,
        ultimo_consejo=ultimo,
        sin_cargo=[j for j in integrantes if not porta.get(j.id)],
    )
