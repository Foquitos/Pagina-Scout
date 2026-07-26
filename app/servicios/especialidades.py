"""Las especialidades de la Rama Scouts (cap. 9).

Una especialidad es un recorrido personal de dos a seis meses por un tema que a
la persona le interesa. Dura poco de explicar y mucho de hacer:

    la pide el joven  →  el equipo la prepara  →  el joven la recorre  →  el
                                                   equipo la da por concluida

**La pide el joven, y pide la que quiere.** «Tanto la decisión de desarrollar una
especialidad como la elección del tema específico son personales y voluntarias de
cada joven», y el único requisito es que lo desee. Por eso el pedido es texto
libre y no una lista: si a alguien le interesa la apicultura, escribe apicultura.
Un catálogo cerrado convertiría en «no se puede» todo lo que a los adultos no se
les ocurrió, que es lo contrario de lo que la guía busca acá.

**Pero el trabajo lo hace el equipo.** Pedirla no es empezarla. La guía les
encarga a los educadores conocer el tema, contactar a la persona experta e
informarle el sentido de las especialidades en el Programa de Jóvenes, y pensar
qué se espera en cada una de las tres fases. Eso es `preparar()`, y hasta que
pasa, la especialidad está pedida y nada más.

Los requisitos se escriben **para esa persona**: «son solo una referencia,
pudiendo ser modificadas, teniendo en cuenta las particularidades de cada joven,
así como las diferencias geográficas, culturales, económicas y sociales».

Acá no hay puntaje ni validación automática. El reto del día se entrega y suma
puntos para la patrulla; una especialidad no: se acompaña. `servicios/retos.py`
excluye a propósito los desafíos de especialidad del reto diario, justamente
porque no son cosas que se resuelvan en una tarde.

Las tres fases son las de la guía, con su verbo:

    exploración (conocer)  →  taller (hacer)  →  desafío (servir)

La última no es un examen: es poner lo aprendido al servicio de otro —la
patrulla, la familia, el barrio—, y es lo que hace que una especialidad scout no
sea un curso.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DESAFIO_ESPECIALIDAD,
    FASE_DESAFIO,
    FASE_EXPLORACION,
    FASE_TALLER,
    FASES_ESPECIALIDAD,
    Competencia,
    Desafio,
    Especialidad,
    Usuario,
)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# --- Lo que pide el joven -----------------------------------------------------


def de(sesion: Session, joven: Usuario) -> list[Especialidad]:
    """Las de una persona: primero las que están en curso."""
    return list(
        sesion.scalars(
            select(Especialidad)
            .where(Especialidad.joven_id == joven.id)
            .order_by(Especialidad.lograda, Especialidad.pedida_en.desc())
        )
    )


def pedir(
    sesion: Session, joven: Usuario, nombre: str, motivo: str = "", icono: str = ""
) -> Especialidad:
    """El joven pide la especialidad que quiera. Pedirla es avisarle al equipo.

    Si ya pidió una con el mismo nombre se devuelve esa: pedir dos veces lo mismo
    es entusiasmo, no una especialidad nueva.
    """
    limpio = nombre.strip()[:120]
    if not limpio:
        raise ValueError("Escribí qué especialidad querés hacer.")

    ya = sesion.scalar(
        select(Especialidad).where(
            Especialidad.joven_id == joven.id,
            Especialidad.nombre == limpio,
            Especialidad.lograda.is_(False),
        )
    )
    if ya is not None:
        return ya

    especialidad = Especialidad(
        joven_id=joven.id,
        nombre=limpio,
        icono=(icono.strip() or "⭐")[:10],
        motivo=motivo.strip(),
        fase=FASE_EXPLORACION,
    )
    sesion.add(especialidad)
    sesion.flush()
    return especialidad


def escribir(especialidad: Especialidad, fase: str, texto: str) -> None:
    """Guarda lo escrito en una fase y adelanta el cartel si corresponde.

    La fase que muestra la pantalla es la más avanzada que tenga algo escrito.
    No se le pide a nadie que apriete «siguiente»: si contaste lo que hiciste en
    el taller, es que estás en el taller.
    """
    if fase not in FASES_ESPECIALIDAD:
        raise ValueError("Esa fase no existe.")
    setattr(especialidad, fase, texto.strip())

    escrito = especialidad.escrito
    for candidata in (FASE_DESAFIO, FASE_TALLER, FASE_EXPLORACION):
        if escrito[candidata].strip():
            especialidad.fase = candidata
            return
    especialidad.fase = FASE_EXPLORACION


def sugerencias(sesion: Session, tope: int = 40) -> list[tuple[str, str]]:
    """Ideas sacadas de las propias cartas: (texto del desafío, carta).

    Los desafíos marcados como especialidad dentro de las Cartas de Exploración
    ya son una lista de temas posibles escrita por la Asociación. Se muestran
    como ideas para quien no sabe por dónde empezar, **nunca como las únicas
    opciones**: el campo sigue siendo libre.
    """
    filas = sesion.execute(
        select(Desafio.texto, Competencia.titulo)
        .join(Competencia, Competencia.id == Desafio.competencia_id)
        .where(Desafio.tipo == DESAFIO_ESPECIALIDAD)
        .order_by(Competencia.numero, Desafio.orden)
        .limit(tope)
    )
    return [(texto, carta) for texto, carta in filas]


# --- Lo que hace el equipo ----------------------------------------------------


def preparar(
    especialidad: Especialidad,
    educador: Usuario,
    experto: str = "",
    pide_exploracion: str = "",
    pide_taller: str = "",
    pide_desafio: str = "",
) -> None:
    """El equipo responde al pedido: qué se espera en cada fase y quién acompaña.

    Es el trabajo que la guía les encarga a los educadores, y recién con esto
    hecho la especialidad se puede recorrer. Se puede volver a preparar cuantas
    veces haga falta: ajustar lo pedido a la realidad de la persona es
    exactamente lo que la guía pide.
    """
    especialidad.experto = experto.strip()[:120]
    especialidad.pide_exploracion = pide_exploracion.strip()
    especialidad.pide_taller = pide_taller.strip()
    especialidad.pide_desafio = pide_desafio.strip()
    if especialidad.preparada_en is None:
        especialidad.preparada_en = _ahora()
    especialidad.preparada_por_id = educador.id


def lograr(especialidad: Especialidad, quien: Usuario, nota: str = "") -> None:
    """La insignia se entrega al terminar, «al finalizar el proceso».

    La da un educador y no la aplicación: es lo único de la progresión personal
    que la guía deja explícitamente del lado del equipo, porque la insignia
    «constituye un testimonio permanente de la actitud de servicio» y eso lo
    atestigua alguien, no un contador de campos completos.
    """
    especialidad.lograda = True
    especialidad.lograda_en = _ahora()
    especialidad.lograda_por_id = quien.id
    especialidad.nota_cierre = nota.strip()


def reabrir(especialidad: Especialidad) -> None:
    especialidad.lograda = False
    especialidad.lograda_en = None
    especialidad.lograda_por_id = None
    especialidad.nota_cierre = ""


def en_curso(sesion: Session, unidad_id: int) -> list[Especialidad]:
    """Todo lo que hay dando vueltas en la Unidad, sin cerrar.

    Lo pedido primero: es lo que espera una respuesta del equipo.
    """
    todas = list(
        sesion.scalars(
            select(Especialidad)
            .join(Usuario, Usuario.id == Especialidad.joven_id)
            .where(
                Usuario.unidad_id == unidad_id,
                Usuario.activo.is_(True),
                Especialidad.lograda.is_(False),
            )
            .order_by(Especialidad.pedida_en)
        )
    )
    return sorted(todas, key=lambda e: e.preparada)


def sin_preparar(sesion: Session, unidad_id: int) -> list[Especialidad]:
    """Las que alguien pidió y el equipo todavía no contestó."""
    return [e for e in en_curso(sesion, unidad_id) if not e.preparada]


def listas_para_cerrar(sesion: Session, unidad_id: int) -> list[Especialidad]:
    """Las que llegaron a la fase de servicio y todavía no se entregaron."""
    return [
        e for e in en_curso(sesion, unidad_id) if e.preparada and e.fase == FASE_DESAFIO
    ]
