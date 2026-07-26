"""Progresión personal: las cartas que eligió cada joven y cómo viene.

Acá no hay puntaje. Una carta no se "gana": se recorre, y el cierre lo
conversan el joven, su patrulla y el equipo de educadores (cap. 9). Por eso el
avance se cuenta sobre los desafíos **requeridos** —los mínimos de la carta— y
los opcionales se muestran aparte, sumando pero sin cambiar la meta.

Las cartas y la etapa van de la mano: las cartas de la etapa son el recorrido
que se propuso el joven, y son lo que el equipo mira para decidir el paso a la
etapa siguiente. Pero ninguna de las dos cosas se cierra sola. Las dos las
decide un educador, y este módulo se ocupa de que ninguna se decida a ciegas:
cuando lo que se pide no coincide con lo marcado —una carta con requeridos sin
hacer, una etapa sin las cartas mínimas logradas— levanta
`NecesitaConfirmacion` en vez de negarse. La guía es explícita en que el
acompañamiento es personalizado y en que hay razones legítimas para cerrar algo
que el papel muestra incompleto; lo que no puede pasar es que ocurra sin que
nadie lo haya mirado.

Cambiar de etapa no borra nada. Las cartas y las marcas viven atadas a la etapa
en la que se trabajaron, así que al cambiar quedan enteras y salen por el
historial. Las que llegó a lograr, además, no vuelven al catálogo: una
competencia desarrollada no se vuelve a elegir.

Lo que sí es visible para otros es el recorrido, nunca un número comparable
entre personas: `/mi-patrulla` lista a la patrulla por nombre, no por avance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.models import (
    DESAFIO_REQUERIDO,
    ETAPAS,
    ETAPAS_NOMBRE,
    AvanceDesafio,
    CambioEtapa,
    Competencia,
    CompetenciaElegida,
    Desafio,
    Usuario,
)

# Cuántas cartas elige cada joven para su etapa (cap. 9).
MIN_CARTAS = 12
MAX_CARTAS = 14


class NecesitaConfirmacion(Exception):
    """Se puede hacer, pero no en silencio: que el educador lo confirme.

    No es un "no". Es la diferencia entre el camino de siempre y una decisión
    que alguien tiene que tomar a propósito.
    """

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


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
    # Las marcas de la etapa de esta carta, por id de desafío. Van adentro
    # porque el historial mezcla cartas de etapas distintas en una misma
    # pantalla, y cada una tiene que leerse con las marcas que le tocan.
    marcas: dict[int, AvanceDesafio]

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
    def requeridos_pendientes(self) -> int:
        return max(0, self.requeridos - self.requeridos_hechos)

    @property
    def sin_empezar(self) -> bool:
        return self.hechos == 0 and self.comentarios == 0

    @property
    def lista_para_cerrar(self) -> bool:
        """Cumplió los requeridos y todavía nadie la cerró: hay algo que conversar."""
        return self.completa and not self.elegida.lograda


def marcas_de(
    sesion: Session, joven: Usuario, etapa: str | None = None
) -> dict[int, AvanceDesafio]:
    """Lo marcado por un joven en una etapa —la actual salvo que se pida otra—."""
    consulta = select(AvanceDesafio).where(
        AvanceDesafio.joven_id == joven.id,
        AvanceDesafio.etapa == (etapa or joven.etapa),
    )
    return {a.desafio_id: a for a in sesion.scalars(consulta)}


def marcas_por_etapa(sesion: Session, joven: Usuario) -> dict[str, dict[int, AvanceDesafio]]:
    """Todo lo que escribió alguna vez, agrupado por etapa.

    Es el insumo del historial: una carta de una etapa vieja tiene que contarse
    con las marcas de esa etapa, no con las de ahora.
    """
    marcas: dict[str, dict[int, AvanceDesafio]] = {}
    consulta = select(AvanceDesafio).where(AvanceDesafio.joven_id == joven.id)
    for avance in sesion.scalars(consulta):
        marcas.setdefault(avance.etapa, {})[avance.desafio_id] = avance
    return marcas


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
        marcas=marcas,
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


def carta_elegida(
    sesion: Session, joven: Usuario, competencia_id: int
) -> CompetenciaElegida | None:
    """La elección de esa carta en la etapa actual del joven, si la tiene."""
    return sesion.scalar(
        select(CompetenciaElegida).where(
            CompetenciaElegida.joven_id == joven.id,
            CompetenciaElegida.competencia_id == competencia_id,
            CompetenciaElegida.etapa == joven.etapa,
        )
    )


# --- Lo que quedó de las etapas anteriores -----------------------------------


@dataclass
class EtapaCumplida:
    """Una etapa ya recorrida, con las cartas que quedaron de ella."""

    etapa: str
    logradas: list[AvanceCarta]
    sin_cerrar: list[AvanceCarta]

    @property
    def nombre(self) -> str:
        return ETAPAS_NOMBRE.get(self.etapa, self.etapa)

    @property
    def cartas(self) -> list[AvanceCarta]:
        return self.logradas + self.sin_cerrar

    @property
    def anotaciones(self) -> int:
        return sum(a.comentarios for a in self.cartas)


def logradas_de_otras_etapas(
    sesion: Session, joven: Usuario
) -> dict[int, CompetenciaElegida]:
    """Las competencias que ya logró en otra etapa, por id de competencia.

    Una competencia lograda no se vuelve a elegir: ya la desarrolló. Por eso
    estas salen del catálogo en vez de quedar ahí ofreciéndose de nuevo, y por
    eso el historial existe: lo que sale de la vista tiene que estar en algún
    lado.
    """
    filas = sesion.scalars(
        select(CompetenciaElegida).where(
            CompetenciaElegida.joven_id == joven.id,
            CompetenciaElegida.etapa != joven.etapa,
            CompetenciaElegida.lograda.is_(True),
        )
    )
    return {f.competencia_id: f for f in filas}


def carta_de_otra_etapa(
    sesion: Session, joven: Usuario, competencia_id: int
) -> CompetenciaElegida | None:
    """La carta lograda en otra etapa, si esa competencia ya la tiene cerrada.

    Si hay más de una —volvió a una etapa anterior y la logró en las dos—, la
    más reciente: es la que cuenta como cierre de esa competencia.
    """
    return sesion.scalar(
        select(CompetenciaElegida)
        .where(
            CompetenciaElegida.joven_id == joven.id,
            CompetenciaElegida.competencia_id == competencia_id,
            CompetenciaElegida.etapa != joven.etapa,
            CompetenciaElegida.lograda.is_(True),
        )
        .order_by(CompetenciaElegida.lograda_en.desc(), CompetenciaElegida.id.desc())
    )


def _orden_de_etapa(etapa: str) -> int:
    """Para ordenar el historial como se recorrió, no como salió de la base."""
    return ETAPAS.index(etapa) if etapa in ETAPAS else len(ETAPAS)


def historial_de_cartas(sesion: Session, joven: Usuario) -> list[EtapaCumplida]:
    """Las cartas de las otras etapas, con todo lo que escribió en cada desafío.

    Cambiar de etapa no borra nada: las cartas viven atadas a la etapa en la que
    se trabajaron, así que acá siguen enteras. Van las logradas —lo que el
    historial viene a guardar— y también las que quedaron sin cerrar, porque
    ahí también hay trabajo hecho y no tiene por qué desaparecer de la pantalla.
    """
    filas = list(
        sesion.scalars(
            select(CompetenciaElegida)
            .where(
                CompetenciaElegida.joven_id == joven.id,
                CompetenciaElegida.etapa != joven.etapa,
            )
            .order_by(CompetenciaElegida.elegida_en, CompetenciaElegida.id)
        )
    )
    if not filas:
        return []

    marcas = marcas_por_etapa(sesion, joven)
    por_etapa: dict[str, list[CompetenciaElegida]] = {}
    for fila in filas:
        por_etapa.setdefault(fila.etapa, []).append(fila)

    historial = []
    for etapa in sorted(por_etapa, key=_orden_de_etapa):
        avances = [avance_de_carta(f, marcas.get(etapa, {})) for f in por_etapa[etapa]]
        historial.append(
            EtapaCumplida(
                etapa=etapa,
                logradas=[a for a in avances if a.elegida.lograda],
                sin_cerrar=[a for a in avances if not a.elegida.lograda],
            )
        )
    return historial


# --- Cómo viene la etapa -----------------------------------------------------


@dataclass
class AvanceEtapa:
    """La etapa de un joven vista entera: es lo que se mira para cambiarla."""

    joven: Usuario
    avances: list[AvanceCarta]

    @property
    def elegidas(self) -> int:
        return len(self.avances)

    @property
    def logradas(self) -> int:
        return sum(1 for a in self.avances if a.elegida.lograda)

    @property
    def cerradas_con_pendientes(self) -> int:
        return sum(1 for a in self.avances if a.elegida.con_pendientes)

    @property
    def listas_para_cerrar(self) -> int:
        """Cumplió los requeridos y falta la conversación de cierre."""
        return sum(1 for a in self.avances if a.lista_para_cerrar)

    @property
    def eleccion_completa(self) -> bool:
        return MIN_CARTAS <= self.elegidas <= MAX_CARTAS

    @property
    def faltan_para_avanzar(self) -> int:
        """Cuántas cartas logradas faltan para el mínimo de la etapa."""
        return max(0, MIN_CARTAS - self.logradas)

    @property
    def listo_para_avanzar(self) -> bool:
        return self.faltan_para_avanzar == 0

    @property
    def etapa_nombre(self) -> str:
        return ETAPAS_NOMBRE.get(self.joven.etapa, self.joven.etapa)

    @property
    def motivo_pendiente(self) -> str:
        """Qué le falta, en una frase, para el aviso del formulario."""
        if self.listo_para_avanzar:
            return ""
        if not self.elegidas:
            return f"Todavía no eligió ninguna carta para la etapa {self.etapa_nombre}."
        return (
            f"Lleva {self.logradas} de las {MIN_CARTAS} cartas logradas de la etapa "
            f"{self.etapa_nombre}: le faltan {self.faltan_para_avanzar}."
        )


def resumen_de_etapa(sesion: Session, joven: Usuario) -> AvanceEtapa:
    return AvanceEtapa(joven=joven, avances=cartas_elegidas(sesion, joven))


def conteo_por_joven(sesion: Session, jovenes: list[Usuario]) -> dict[int, tuple[int, int]]:
    """(elegidas, logradas) de cada joven en su etapa actual, en una sola consulta.

    El listado de la Unidad necesita el número, no el detalle: traer las cartas
    de treinta personas para contarlas sería pagar de más.
    """
    ids = [j.id for j in jovenes]
    if not ids:
        return {}
    filas = sesion.execute(
        select(
            CompetenciaElegida.joven_id,
            func.count(CompetenciaElegida.id),
            func.sum(cast(CompetenciaElegida.lograda, Integer)),
        )
        .join(
            Usuario,
            (Usuario.id == CompetenciaElegida.joven_id)
            & (Usuario.etapa == CompetenciaElegida.etapa),
        )
        .where(CompetenciaElegida.joven_id.in_(ids))
        .group_by(CompetenciaElegida.joven_id)
    )
    conteos = {joven_id: (elegidas, logradas or 0) for joven_id, elegidas, logradas in filas}
    return {j.id: conteos.get(j.id, (0, 0)) for j in jovenes}


def historial_de_etapas(sesion: Session, joven: Usuario) -> list[CambioEtapa]:
    return list(
        sesion.scalars(
            select(CambioEtapa)
            .where(CambioEtapa.joven_id == joven.id)
            .order_by(CambioEtapa.creado_en.desc(), CambioEtapa.id.desc())
        )
    )


# --- Lo que decide el educador -----------------------------------------------


def cerrar_carta(
    elegida: CompetenciaElegida,
    avance: AvanceCarta,
    educador: Usuario,
    nota: str = "",
    confirmado: bool = False,
) -> None:
    """Da una carta por lograda. Sin todos los requeridos, pide confirmar.

    Que falten requeridos no la vuelve imposible: un desafío opcional puede
    reemplazar a uno requerido si se conversó, y hay chicos que hicieron la
    competencia sin haber ido tildando la lista. Lo que no puede es pasar
    inadvertido.
    """
    if not avance.completa and not confirmado:
        raise NecesitaConfirmacion(_faltan_requeridos(avance))

    elegida.lograda = True
    elegida.lograda_en = _ahora()
    elegida.lograda_por_id = educador.id
    elegida.con_pendientes = not avance.completa
    elegida.nota_cierre = nota.strip()


def reabrir_carta(elegida: CompetenciaElegida) -> None:
    """Vuelve atrás un cierre. Lo marcado adentro de la carta no se toca."""
    elegida.lograda = False
    elegida.lograda_en = None
    elegida.lograda_por_id = None
    elegida.con_pendientes = False
    elegida.nota_cierre = ""


def _faltan_requeridos(avance: AvanceCarta) -> str:
    faltan = avance.requeridos_pendientes
    return (
        f"Le {'falta' if faltan == 1 else 'faltan'} {faltan} desafío"
        f"{'' if faltan == 1 else 's'} requerido{'' if faltan == 1 else 's'} "
        f"sin marcar en esta carta."
    )


def cambiar_etapa(
    sesion: Session,
    joven: Usuario,
    etapa_nueva: str,
    educador: Usuario,
    nota: str = "",
    confirmado: bool = False,
) -> CambioEtapa | None:
    """Mueve a un joven de etapa y deja el registro de quién y con qué números.

    Avanzar con las cartas de la etapa logradas es el camino esperado y sale
    derecho. Cualquier otra cosa —avanzar con cartas pendientes, o volver a una
    etapa anterior— se puede, pero la confirma el educador.

    Devuelve `None` si la etapa pedida es la que ya tenía.
    """
    if etapa_nueva not in ETAPAS:
        raise ValueError("Etapa desconocida.")
    if etapa_nueva == joven.etapa:
        return None

    resumen = resumen_de_etapa(sesion, joven)
    avanza = ETAPAS.index(etapa_nueva) > ETAPAS.index(joven.etapa)
    esperado = avanza and resumen.listo_para_avanzar
    if not esperado and not confirmado:
        raise NecesitaConfirmacion(
            resumen.motivo_pendiente
            if avanza
            else f"Volver a la etapa {ETAPAS_NOMBRE[etapa_nueva]} es ir para atrás en su progresión."
        )

    cambio = CambioEtapa(
        joven_id=joven.id,
        etapa_anterior=joven.etapa,
        etapa_nueva=etapa_nueva,
        educador_id=educador.id,
        cartas_elegidas=resumen.elegidas,
        cartas_logradas=resumen.logradas,
        con_pendientes=not esperado,
        nota=nota.strip(),
    )
    joven.etapa = etapa_nueva
    sesion.add(cambio)
    return cambio
