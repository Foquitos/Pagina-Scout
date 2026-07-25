"""Progresión personal: las cartas que eligió cada joven y cómo viene.

Acá no hay puntaje. Una carta no se "gana": se recorre, y el cierre lo
conversan el joven, su patrulla y el equipo de educadores (cap. 9). Por eso el
avance se cuenta sobre los desafíos **requeridos** —los mínimos de la carta— y
los opcionales se muestran aparte, sumando pero sin cambiar la meta.

Lo que sí es visible para otros es el recorrido, nunca un número comparable
entre personas: `/mi-patrulla` lista a la patrulla por nombre, no por avance.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DESAFIO_REQUERIDO,
    AvanceDesafio,
    Competencia,
    CompetenciaElegida,
    Desafio,
    Usuario,
)


@dataclass
class AvanceCarta:
    """Cómo viene una carta elegida, ya contado para la plantilla."""

    elegida: CompetenciaElegida
    competencia: Competencia
    requeridos: int
    requeridos_hechos: int
    opcionales: int
    opcionales_hechos: int
    comentarios: int

    @property
    def hechos(self) -> int:
        return self.requeridos_hechos + self.opcionales_hechos

    @property
    def total(self) -> int:
        return self.requeridos + self.opcionales

    @property
    def porcentaje(self) -> int:
        """Sobre los requeridos: son los que definen si la carta está cumplida."""
        if not self.requeridos:
            return 100 if self.opcionales_hechos else 0
        return round(100 * self.requeridos_hechos / self.requeridos)

    @property
    def completa(self) -> bool:
        """Todos los requeridos marcados. No la da por lograda: eso se conversa."""
        return self.requeridos > 0 and self.requeridos_hechos == self.requeridos

    @property
    def sin_empezar(self) -> bool:
        return self.hechos == 0 and self.comentarios == 0


def marcas_de(sesion: Session, joven: Usuario) -> dict[int, AvanceDesafio]:
    """Lo marcado por un joven en su etapa actual, por id de desafío."""
    consulta = select(AvanceDesafio).where(
        AvanceDesafio.joven_id == joven.id, AvanceDesafio.etapa == joven.etapa
    )
    return {a.desafio_id: a for a in sesion.scalars(consulta)}


def _contar(competencia: Competencia, marcas: dict[int, AvanceDesafio]) -> tuple[int, ...]:
    requeridos = requeridos_hechos = opcionales = opcionales_hechos = comentarios = 0
    for desafio in competencia.desafios:
        marca = marcas.get(desafio.id)
        es_requerido = desafio.tipo == DESAFIO_REQUERIDO
        if es_requerido:
            requeridos += 1
        else:
            opcionales += 1
        if marca is not None:
            if marca.hecho:
                if es_requerido:
                    requeridos_hechos += 1
                else:
                    opcionales_hechos += 1
            if marca.comentario:
                comentarios += 1
    return requeridos, requeridos_hechos, opcionales, opcionales_hechos, comentarios


def avance_de_carta(
    elegida: CompetenciaElegida, marcas: dict[int, AvanceDesafio]
) -> AvanceCarta:
    competencia = elegida.competencia
    req, req_hechos, opc, opc_hechos, comentarios = _contar(competencia, marcas)
    return AvanceCarta(
        elegida=elegida,
        competencia=competencia,
        requeridos=req,
        requeridos_hechos=req_hechos,
        opcionales=opc,
        opcionales_hechos=opc_hechos,
        comentarios=comentarios,
    )


def cartas_elegidas(sesion: Session, joven: Usuario) -> list[AvanceCarta]:
    """Las cartas de la etapa actual, en el orden en que las fue eligiendo."""
    elegidas = list(
        sesion.scalars(
            select(CompetenciaElegida)
            .where(
                CompetenciaElegida.joven_id == joven.id,
                CompetenciaElegida.etapa == joven.etapa,
            )
            .order_by(CompetenciaElegida.elegida_en, CompetenciaElegida.id)
        )
    )
    if not elegidas:
        return []
    marcas = marcas_de(sesion, joven)
    return [avance_de_carta(e, marcas) for e in elegidas]


def desafios_de(sesion: Session, competencia_id: int) -> list[Desafio]:
    return list(
        sesion.scalars(
            select(Desafio)
            .where(Desafio.competencia_id == competencia_id)
            .order_by(Desafio.orden)
        )
    )
