"""Los cumpleaños de la Unidad.

Un campo con la fecha de nacimiento guardado en una ficha que nadie abre no le
sirve a nadie. Lo que sirve es que el sábado a la mañana la patrulla sepa que el
martes cumple años alguien, y para eso hay que calcular **el próximo**, que no es
la fecha guardada: es la misma fecha llevada al año que viene cuando la de este
año ya pasó.

Dos decisiones sobre qué se muestra y a quién:

**El año no es de todos.** A la Unidad entera se le dice el día y el mes —que es
lo que hace falta para saludar— y la edad queda para el equipo de educadores, que
la necesita: en la Rama Scouts la edad conversa con la etapa y saber que alguien
cumple quince es saber que se viene su pasaje. Guardamos un dato personal de un
menor más que antes; mostrarlo entero a treinta personas cuando alcanza con la
mitad sería regalarlo.

**Cargarlo es opcional y se queda así.** Quien no lo dio no aparece en ninguna
lista y no le falta nada: la cuenta funciona igual. Por eso todo acá filtra por
`nacimiento is not None` en vez de dar por sentado que está.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Usuario


@dataclass(frozen=True)
class Cumple:
    """Un cumpleaños que viene, ya resuelto para no hacer cuentas en la plantilla."""

    usuario: Usuario
    fecha: date  # la próxima vez que cae, no la de nacimiento
    faltan: int
    cumple: int  # cuántos años cumple ese día

    @property
    def es_hoy(self) -> bool:
        return self.faltan == 0


def _proxima_vez(nacimiento: date, desde: date) -> date:
    """Cuándo cae el próximo cumpleaños a partir de `desde` (incluido).

    El 29 de febrero no existe tres de cada cuatro años. Se pasa al 1 de marzo y
    no al 28: quien nació un 29 cumple cuando febrero terminó, y además así no se
    le pisa el cumpleaños a nadie que sí haya nacido un 28.
    """
    def en_el_ano(ano: int) -> date:
        try:
            return nacimiento.replace(year=ano)
        except ValueError:
            return date(ano, 3, 1)

    este_ano = en_el_ano(desde.year)
    return este_ano if este_ano >= desde else en_el_ano(desde.year + 1)


def proximos(
    sesion: Session, unidad_id: int, desde: date, dias: int = 30, tope: int = 8
) -> list[Cumple]:
    """Los que caen en los próximos `dias`, el más cercano primero.

    Incluye al equipo de educadores: son parte de la Unidad y también cumplen
    años. Deja afuera a quien esté dado de baja —no está para que lo saluden— y
    a quien no cargó la fecha.
    """
    gente = sesion.scalars(
        select(Usuario).where(
            Usuario.unidad_id == unidad_id,
            Usuario.activo.is_(True),
            Usuario.nacimiento.is_not(None),
        )
    )

    proximos_: list[Cumple] = []
    for persona in gente:
        cae = _proxima_vez(persona.nacimiento, desde)
        faltan = (cae - desde).days
        if faltan > dias:
            continue
        proximos_.append(
            Cumple(
                usuario=persona,
                fecha=cae,
                faltan=faltan,
                cumple=cae.year - persona.nacimiento.year,
            )
        )

    # Por fecha y después por nombre: dos que cumplen el mismo día salen siempre
    # en el mismo orden, que es lo que evita que la lista baile entre recargas.
    proximos_.sort(key=lambda c: (c.faltan, c.usuario.nombre))
    return proximos_[:tope]


def de_hoy(sesion: Session, unidad_id: int, hoy: date) -> list[Cumple]:
    """Solo los de hoy. Es lo que va arriba de todo cuando hay alguno."""
    return [c for c in proximos(sesion, unidad_id, hoy, dias=0) if c.es_hoy]
