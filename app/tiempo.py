"""La hora de la Unidad.

Dos reglas, y de ellas sale todo lo demás:

* Lo que se guarda va en UTC. Una marca de tiempo no puede depender de dónde
  esté parado el servidor —el contenedor de Azure corre en UTC, la notebook de
  quien programa en Buenos Aires— ni de que mañana el país cambie de huso.

* Lo que se muestra sale en la zona horaria de la Unidad, GMT-3 en Argentina.
  Nadie escribe una entrega «a las 22:30 UTC»: la escribió a las 19:30, que es
  la hora que marcaba el reloj de la cocina.

La traducción entre las dos pasa una sola vez, acá, cuando se pinta la
pantalla. En la base nunca hay horas locales.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.config import ZONA_HORARIA


def ahora() -> datetime:
    """El instante de ahora, en UTC y con su zona puesta: lo que se guarda."""
    return datetime.now(timezone.utc)


def hoy() -> date:
    """El día de hoy en la zona horaria de la Unidad, no la del servidor.

    Importa de verdad entre las 21 y la medianoche: en UTC ya es mañana, y un
    reto que se entrega a las 22 tiene que contar para el día que fue.
    """
    return datetime.now(ZONA_HORARIA).date()


def local(momento: datetime | None) -> datetime | None:
    """Una marca de tiempo guardada, llevada a la hora de la Unidad.

    SQLite no guarda la zona: lo que vuelve de la base es un `datetime` pelado.
    Está en UTC, porque en UTC se escribió, así que primero se le devuelve la
    zona que le corresponde y recién después se traduce.
    """
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(ZONA_HORARIA)


def hora(momento: datetime | None, formato: str = "%d/%m/%Y %H:%M") -> str:
    """El filtro de las plantillas: la marca en hora de la Unidad, ya escrita.

    En las plantillas se usa ``{{ e.enviada_en | hora('%d/%m/%Y %H:%M') }}`` en
    lugar de `strftime` a secas, que muestra la hora de UTC. Los campos que son
    de día —una fecha de asignación, un cumpleaños— no pasan por acá: no tienen
    hora que convertir.
    """
    momento = local(momento)
    return momento.strftime(formato) if momento else ""
