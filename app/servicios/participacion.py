"""Ideas: qué quiere hacer la Unidad (cap. 8).

El Ciclo de Programa es el mecanismo por el que las chicas y los chicos deciden
qué va a hacer su Unidad. La guía lo dice sin rodeos: «En nuestra organización,
las y los jóvenes tienen voz y voto respecto de las actividades que desean
realizar», y describe la alternativa —una Unidad «en las que todo está decidido
por las personas adultas»— como lo que hay que evitar.

**La Asamblea no está acá, y es a propósito.** Se reúne en persona y así tiene
que seguir: es donde se aprende a defender una idea, a escuchar la de otro y a
bancarse perder una votación mirando a la cara al que la ganó. Eso una pantalla
no lo enseña. Lo que la aplicación hace es lo que un papelito en el bolsillo hace
mal: juntar las propuestas para que lleguen enteras a esa reunión, y anotar
después lo que la Unidad decidió ahí.

De ahí el recorrido:

    alguien la propone  →  el equipo mira si se puede  →  la Asamblea decide
                                                          (en persona)
                                                       →  se anota y va al calendario

`apoyos` («me sumo») no es un voto y no decide nada: es un dato para llevar a la
reunión, saber cuántos la quieren antes de discutirla.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ALCANCE_PATRULLA,
    ALCANCE_UNIDAD,
    CLASES_ACTIVIDAD,
    IDEA_ELEGIDA,
    IDEA_GUARDADA,
    IDEA_POSIBLE,
    IDEA_PROPUESTA,
    IDEAS_ESTADO,
    ApoyoIdea,
    Idea,
    Usuario,
)


class NoLeToca(Exception):
    """Lo pidió alguien que en el método no tiene esa atribución."""


# --- Proponer -----------------------------------------------------------------


def proponer(
    sesion: Session,
    autor: Usuario,
    titulo: str,
    texto: str,
    hace_falta: str,
    clase: str,
    ambito: str,
) -> Idea:
    """Alguien tira una idea. Cuesta poco a propósito.

    Una propuesta que exige un formulario largo no se escribe. Con el título
    alcanza; lo demás se completa después, o lo completa la patrulla cuando la
    discute en el Consejo.
    """
    if not titulo.strip():
        raise ValueError("La idea necesita un título.")
    if autor.unidad_id is None:
        raise ValueError("Para proponer algo hay que estar en una Unidad.")
    if clase not in CLASES_ACTIVIDAD:
        clase = CLASES_ACTIVIDAD[0]
    if ambito not in (ALCANCE_UNIDAD, ALCANCE_PATRULLA):
        ambito = ALCANCE_UNIDAD

    idea = Idea(
        unidad_id=autor.unidad_id,
        patrulla_id=autor.patrulla_id,
        autor_id=autor.id,
        titulo=titulo.strip()[:200],
        texto=texto.strip(),
        hace_falta=hace_falta.strip(),
        clase=clase,
        ambito=ambito,
    )
    sesion.add(idea)
    sesion.flush()
    return idea


def ideas_de_unidad(
    sesion: Session, unidad_id: int, estados: tuple[str, ...] | None = None
) -> list[Idea]:
    consulta = select(Idea).where(Idea.unidad_id == unidad_id)
    if estados:
        consulta = consulta.where(Idea.estado.in_(estados))
    return list(sesion.scalars(consulta.order_by(Idea.creada_en.desc())))


# --- «Me sumo» ----------------------------------------------------------------


def apoyos_de(sesion: Session, ideas: list[Idea]) -> dict[int, int]:
    """Cuántos «me sumo» tiene cada idea, en una sola consulta."""
    if not ideas:
        return {}
    filas = sesion.execute(
        select(ApoyoIdea.idea_id, func.count(ApoyoIdea.id))
        .where(ApoyoIdea.idea_id.in_([i.id for i in ideas]))
        .group_by(ApoyoIdea.idea_id)
    )
    return {idea_id: cuenta for idea_id, cuenta in filas}


def apoyos_propios(sesion: Session, joven: Usuario, ideas: list[Idea]) -> set[int]:
    if not ideas:
        return set()
    return set(
        sesion.scalars(
            select(ApoyoIdea.idea_id).where(
                ApoyoIdea.joven_id == joven.id,
                ApoyoIdea.idea_id.in_([i.id for i in ideas]),
            )
        )
    )


def alternar_apoyo(sesion: Session, idea: Idea, joven: Usuario) -> bool:
    """«Me sumo» / «me bajo». Devuelve si quedó apoyada."""
    existente = sesion.scalar(
        select(ApoyoIdea).where(
            ApoyoIdea.idea_id == idea.id, ApoyoIdea.joven_id == joven.id
        )
    )
    if existente is not None:
        sesion.delete(existente)
        return False
    sesion.add(ApoyoIdea(idea_id=idea.id, joven_id=joven.id))
    return True


# --- Lo que hace el equipo con una idea --------------------------------------


def mover(idea: Idea, estado: str, respuesta: str = "") -> None:
    """Cambia en qué anda una idea, y por qué.

    Los cuatro estados son los cuatro momentos reales de una propuesta:

    - **propuesta**: alguien la escribió y todavía no la miró nadie.
    - **posible**: el equipo la miró y se puede hacer. Va a la Asamblea.
    - **elegida**: la Asamblea la eligió. Se anota acá después de la reunión.
    - **guardada**: no salió esta vez. No se descarta: vuelve el ciclo que viene.

    La `respuesta` importa sobre todo cuando algo se guarda. A un chico que
    propuso algo se le contesta; que su idea desaparezca sin una palabra es la
    forma más rápida de que no vuelva a proponer nada.
    """
    if estado not in IDEAS_ESTADO:
        raise ValueError("Ese estado no existe.")
    idea.estado = estado
    if respuesta.strip():
        idea.respuesta = respuesta.strip()


def puede_borrar(usuario: Usuario, idea: Idea) -> bool:
    """La borra el equipo, o quien la escribió mientras nadie la haya mirado.

    Arrepentirse de lo que uno escribió tiene que ser barato; borrar la idea de
    otro, no. Una vez que el equipo la marcó, ya no es solo del que la propuso.
    """
    if usuario.es_educador:
        return True
    return idea.autor_id == usuario.id and idea.estado == IDEA_PROPUESTA


def contar_por_estado(sesion: Session, unidad_id: int) -> dict[str, int]:
    filas = sesion.execute(
        select(Idea.estado, func.count(Idea.id))
        .where(Idea.unidad_id == unidad_id)
        .group_by(Idea.estado)
    )
    cuenta = {estado: 0 for estado in IDEAS_ESTADO}
    for estado, total in filas:
        cuenta[estado] = total
    return cuenta


def sin_mirar(sesion: Session, unidad_id: int) -> int:
    """Cuántas propuestas esperan que el equipo las mire."""
    return (
        sesion.scalar(
            select(func.count(Idea.id)).where(
                Idea.unidad_id == unidad_id, Idea.estado == IDEA_PROPUESTA
            )
        )
        or 0
    )


# Se reexportan para que las rutas no tengan que importar de dos lados.
__all__ = [
    "IDEA_ELEGIDA",
    "IDEA_GUARDADA",
    "IDEA_POSIBLE",
    "IDEA_PROPUESTA",
    "NoLeToca",
    "alternar_apoyo",
    "apoyos_de",
    "apoyos_propios",
    "contar_por_estado",
    "ideas_de_unidad",
    "mover",
    "proponer",
    "puede_borrar",
    "sin_mirar",
]
