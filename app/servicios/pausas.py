"""Quién está sin teléfono, y qué se hace mientras tanto.

El problema es viejo y no es de software: en una patrulla de cinco, uno rompe el
celular un martes y hasta que se arregle no puede entregar nada. El tablero
divide los puntos por la cantidad de integrantes, así que esa patrulla pasa dos
semanas dividiendo por cinco lo que hicieron cuatro. Quedan atrás por algo que no
decidió ninguno de ellos, y el que se quedó sin teléfono además mira desde afuera
cómo se le frena la progresión.

Este módulo es la respuesta a las dos mitades:

1. **La pausa.** Un educador registra el tramo. Mientras dure, esa persona no
   entra en el divisor del promedio (`servicios/puntajes.py`) y su patrulla deja
   de pagar por ella. Los puntos que ya había hecho se quedan en el total: los
   hizo, y borrarlos sería la injusticia de al lado.
2. **La entrega dictada.** Que no cuente en el divisor le arregla el número a la
   patrulla, pero al chico no le devuelve nada: sigue sin poder registrar lo que
   hace. Por eso quien está en pausa puede contarle a un educador o a alguien de
   su patrulla lo que hizo, y esa persona lo carga. La entrega es suya —le suma a
   su patrulla y le cuenta para su progresión— y queda firmada por quien la
   escribió.

**Quién puede cargarle a quién** está acá y en un solo lugar: un educador de su
Unidad, o alguien de su misma patrulla. Los compañeros no son un permiso que se
regaló por comodidad: los retos son diarios y el educador no está todos los días,
pero el Guía sí. Es literalmente para lo que existe el sistema de patrullas.

Lo que **no** habilita la pausa: publicar en el muro por otro. Compartir lo
decide quien lo hizo y nadie más (ver `servicios/muro.py`), así que la entrega
dictada nace sin compartir y el interruptor lo aprieta su dueño cuando recupera
el teléfono.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ESTADO_APROBADA,
    ROL_JOVEN,
    Asignacion,
    Entrega,
    PausaSinTelefono,
    Usuario,
)
from app.servicios import retos

# Hasta dónde para atrás se ofrecen retos para cargar. Es un tope de pantalla y
# de sentido común: alguien que estuvo un mes sin teléfono no va a reconstruir
# treinta días de memoria, y una lista de treinta formularios no la llena nadie.
DIAS_PARA_ATRAS = 14

# Sugerencias, no un menú cerrado: van en un `datalist` y se puede escribir
# cualquier otra cosa. Mismo criterio que las especialidades —un catálogo cerrado
# convierte en «no se puede» todo lo que a los adultos no se les ocurrió—, con el
# agregado de que acá adivinar mal el motivo de un chico es meterse donde no va.
MOTIVOS_SUGERIDOS = (
    "Se le rompió el teléfono",
    "Está sin el teléfono en casa",
    "Lo comparte con la familia",
    "Se quedó sin datos",
    "Se lo perdió",
)


# --- Quién está en pausa -------------------------------------------------------


def _vigentes(dia: date):
    """La condición de «vigente en este día», para reusarla en cada consulta.

    `vuelve_el` es el día que lo tiene de vuelta y ese día ya cuenta, así que el
    borde es estricto. Dice lo mismo que `PausaSinTelefono.vigente_en` pero en
    SQL, y las dos formas tienen que decir siempre lo mismo.
    """
    return (
        PausaSinTelefono.desde <= dia,
        or_(PausaSinTelefono.vuelve_el.is_(None), PausaSinTelefono.vuelve_el > dia),
    )


def vigente(sesion: Session, joven_id: int, dia: date) -> PausaSinTelefono | None:
    """La pausa abierta de esta persona ese día, si la hay."""
    return sesion.scalar(
        select(PausaSinTelefono)
        .where(PausaSinTelefono.joven_id == joven_id, *_vigentes(dia))
        .order_by(PausaSinTelefono.desde.desc())
    )


def vigentes_de(
    sesion: Session, jovenes_ids: list[int], dia: date
) -> dict[int, PausaSinTelefono]:
    """Las pausas vigentes de un grupo de personas, por id.

    Una consulta para toda una lista de jóvenes: la pantalla de `/jovenes` y la
    de una patrulla preguntan por veinte a la vez.
    """
    if not jovenes_ids:
        return {}
    filas = sesion.scalars(
        select(PausaSinTelefono).where(
            PausaSinTelefono.joven_id.in_(jovenes_ids), *_vigentes(dia)
        )
    )
    return {p.joven_id: p for p in filas}


def en_pausa_de_unidad(
    sesion: Session, unidad_id: int, dia: date
) -> dict[int, PausaSinTelefono]:
    """Toda la Unidad que hoy está sin teléfono, por id de joven."""
    filas = sesion.scalars(
        select(PausaSinTelefono)
        .join(Usuario, Usuario.id == PausaSinTelefono.joven_id)
        .where(
            Usuario.unidad_id == unidad_id,
            Usuario.rol == ROL_JOVEN,
            Usuario.activo.is_(True),
            *_vigentes(dia),
        )
        .order_by(PausaSinTelefono.desde)
    )
    return {p.joven_id: p for p in filas}


def conteo_por_patrulla(sesion: Session, unidad_id: int, dia: date) -> dict[int, int]:
    """Cuántos están en pausa en cada patrulla. Lo que el tablero saca del divisor.

    Cuenta personas y no pausas (`distinct`): si por un error quedaron dos
    abiertas sobre la misma, sigue siendo una sola cabeza la que no divide.
    """
    filas = sesion.execute(
        select(Usuario.patrulla_id, func.count(func.distinct(Usuario.id)))
        .join(PausaSinTelefono, PausaSinTelefono.joven_id == Usuario.id)
        .where(
            Usuario.unidad_id == unidad_id,
            Usuario.rol == ROL_JOVEN,
            Usuario.activo.is_(True),
            Usuario.patrulla_id.is_not(None),
            *_vigentes(dia),
        )
        .group_by(Usuario.patrulla_id)
    ).all()
    return {int(patrulla_id): int(cuantos) for patrulla_id, cuantos in filas}


def historial(sesion: Session, joven_id: int) -> list[PausaSinTelefono]:
    """Todas las veces que estuvo sin teléfono, lo último primero."""
    return list(
        sesion.scalars(
            select(PausaSinTelefono)
            .where(PausaSinTelefono.joven_id == joven_id)
            .order_by(PausaSinTelefono.desde.desc(), PausaSinTelefono.id.desc())
        )
    )


# --- Abrir y cerrar ------------------------------------------------------------


def abrir(
    sesion: Session,
    joven: Usuario,
    educador: Usuario,
    motivo: str = "",
    desde: date | None = None,
    vuelve_el: date | None = None,
) -> PausaSinTelefono:
    """Registra que esta persona no puede entregar. No hace commit.

    `vuelve_el` se puede dejar puesto de entrada —«lo tiene de vuelta el 20»— y
    entonces la pausa se vence sola. Es el caso más común y el que evita el error
    que importa: alguien que recuperó el teléfono hace un mes y sigue fuera del
    divisor porque nadie se acordó de cerrar nada.
    """
    pausa = PausaSinTelefono(
        joven_id=joven.id,
        motivo=(motivo or "").strip(),
        desde=desde or retos.hoy(),
        vuelve_el=vuelve_el,
        abierta_por_id=educador.id,
    )
    sesion.add(pausa)
    return pausa


def cerrar(pausa: PausaSinTelefono, educador: Usuario, dia: date | None = None) -> None:
    """«Ya tiene el teléfono». Cuenta de nuevo desde ese mismo día. No hace commit.

    Cerrar es ponerle el día de vuelta, no borrar la pausa: que esa semana existió
    es parte de por qué el tablero decía lo que decía, y en dos meses alguien va a
    querer entender ese número.

    El día que vuelve ya cuenta —`vuelve_el` es un borde estricto—, así que
    apretar el botón se nota en el tablero en el momento y no al día siguiente.
    Una pausa abierta y cerrada el mismo día queda con `desde == vuelve_el` y no
    estuvo vigente nunca, que es exactamente lo que pasó.
    """
    pausa.vuelve_el = dia or retos.hoy()
    pausa.cerrada_por_id = educador.id


# --- Cargar lo que hizo otro ---------------------------------------------------


def puede_dictar(quien: Usuario, joven: Usuario, pausa: PausaSinTelefono | None) -> bool:
    """¿Esta persona puede cargar la entrega de esta otra?

    Tres condiciones, y las tres hacen falta:

    - Hay una pausa vigente. Sin eso no se escribe en nombre de nadie: el que
      tiene su teléfono entrega solo, que para eso es suya la evidencia.
    - Es de la misma Unidad.
    - Es un educador, o alguien de su misma patrulla.

    Nadie se dicta a sí mismo: para eso está el formulario de siempre.
    """
    if pausa is None or quien.id == joven.id:
        return False
    if quien.unidad_id is None or quien.unidad_id != joven.unidad_id:
        return False
    if quien.es_educador:
        return True
    return joven.patrulla_id is not None and quien.patrulla_id == joven.patrulla_id


def a_quienes_puede_cargar(
    sesion: Session, quien: Usuario, dia: date
) -> list[tuple[Usuario, PausaSinTelefono]]:
    """De quiénes puede cargar entregas esta persona hoy.

    Para un educador, toda su Unidad; para un joven, su patrulla. Es lo que
    aparece en `/hoy` («Bruno está sin teléfono») y en el panel del equipo.
    """
    if quien.unidad_id is None:
        return []
    pausas = en_pausa_de_unidad(sesion, quien.unidad_id, dia)
    if not pausas:
        return []
    jovenes = sesion.scalars(
        select(Usuario).where(Usuario.id.in_(pausas)).order_by(Usuario.nombre)
    )
    return [
        (joven, pausas[joven.id])
        for joven in jovenes
        if puede_dictar(quien, joven, pausas[joven.id])
    ]


def retos_a_cargar(
    sesion: Session, joven: Usuario, pausa: PausaSinTelefono, hoy: date
) -> list[tuple[Asignacion, Entrega | None]]:
    """Los retos de los días que estuvo sin teléfono, con lo que ya se cargó.

    Arranca cuando arrancó la pausa y nunca más de `DIAS_PARA_ATRAS` atrás. Van
    también los que ya tienen entrega —para poder corregir lo que se escribió
    mal, y para que se vea qué días ya están hechos—, y lo último primero, que es
    lo que alguien va a querer cargar.
    """
    desde = max(pausa.desde, hoy - timedelta(days=DIAS_PARA_ATRAS))
    # El día que vuelve ya no es un día sin teléfono: el último es el anterior.
    ultimo = pausa.vuelve_el - timedelta(days=1) if pausa.vuelve_el else hoy
    hasta = min(hoy, ultimo)
    if desde > hasta:
        return []

    asignaciones = retos.asignaciones_entre(sesion, joven, desde, hasta)
    entregas = retos.entregas_por_asignacion(sesion, joven, asignaciones)
    return [(a, entregas.get(a.id)) for a in asignaciones]


def cuantos_faltan(pares: list[tuple[Asignacion, Entrega | None]]) -> int:
    """De los retos de esos días, cuántos todavía no tienen nada cargado."""
    return sum(
        1 for _, entrega in pares if entrega is None or entrega.estado != ESTADO_APROBADA
    )
