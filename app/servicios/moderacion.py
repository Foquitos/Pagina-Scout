"""Qué se ve, quién lo ve, y cómo se baja.

Acá se publica en el momento. Una foto entra al muro o al Libro de Oro sin que
un adulto la haya mirado antes, y eso es deliberado: la alternativa —que cada
página del libro de una patrulla espere el permiso de un grande— le saca a la
patrulla la propiedad de su propio libro, que es justo lo que el capítulo 4
manda respetar.

Lo que la inmediatez obliga a tener, y es lo que hay en este módulo:

**El equipo se entera.** `novedades()` es todo lo que se publicó en la Unidad,
lo último primero, con la foto a la vista. No es una cola de aprobación —no hay
nada que aprobar, ya está publicado—: es el lugar donde un educador se entera
de lo que está dando vueltas sin tener que recorrer siete libros de patrulla.

**Cualquiera puede avisar.** Sobre todo quien aparece en la foto. Un aviso no
oculta nada por sí solo: pone la publicación arriba de todo para que la mire
una persona.

**Bajar es de una persona y se puede deshacer.** `oculta_en` no borra: la
entrega sigue existiendo con sus puntos y el joven la sigue viendo. Y se puede
devolver, porque un educador que baja algo por error a las once de la noche
tiene que poder arreglarlo sin entrar a la base.

La cuarta pieza es la de más abajo, `puede_ver_foto()`, y no tiene que ver con
moderar sino con la misma pregunta: el archivo de una foto se sirve si y solo si
quien lo pide podría ver la página donde esa foto vive. Antes alcanzaba con
tener sesión, y entonces el link de una foto suelta valía más que el permiso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ESTADO_APROBADA,
    Asignacion,
    Aviso,
    EntradaLibroOro,
    Entrega,
    Patrulla,
    Usuario,
)


class NoSePuede(Exception):
    """Con un motivo escrito para mostrárselo a quien lo intentó."""


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# --- Quién puede ver una foto -------------------------------------------------
#
# Las tres columnas que guardan nombres de archivo no están indexadas y se
# recorren enteras. Con una Unidad —unos miles de entregas y unos cientos de
# páginas de libro— es tiempo que no se mide; si esto alguna vez sirve a varios
# Grupos, acá hay que poner un índice.


def puede_ver_foto(sesion: Session, nombre: str, usuario: Usuario) -> bool:
    """¿`usuario` puede ver el archivo `nombre`?

    Se busca de quién es la foto y se aplica la misma regla que la página donde
    se muestra. Si no es de nadie —un archivo huérfano en el disco— no se sirve:
    lo que ya no está referenciado no tiene por qué seguir siendo accesible.
    """
    if usuario.unidad_id is None:
        return False

    entrega = sesion.scalar(select(Entrega).where(Entrega.archivo_foto == nombre))
    if entrega is not None:
        return _puede_ver_entrega(entrega, usuario)

    pagina = sesion.scalar(
        select(EntradaLibroOro).where(EntradaLibroOro.archivo_foto == nombre)
    )
    if pagina is not None:
        return _puede_ver_pagina(sesion, pagina, usuario)

    patrulla = sesion.scalar(select(Patrulla).where(Patrulla.archivo_banderin == nombre))
    if patrulla is not None:
        return _es_de_la_patrulla(patrulla, usuario)

    return False


def _puede_ver_entrega(entrega: Entrega, usuario: Usuario) -> bool:
    """El autor, el equipo, y la Unidad entera solo si está en el muro."""
    if entrega.joven_id == usuario.id:
        return True
    if entrega.asignacion.unidad_id != usuario.unidad_id:
        return False
    if usuario.es_educador:
        return True
    return entrega.en_el_muro


def _puede_ver_pagina(sesion: Session, pagina: EntradaLibroOro, usuario: Usuario) -> bool:
    """La patrulla y el equipo. Una página bajada, solo el equipo y su autor."""
    patrulla = sesion.get(Patrulla, pagina.patrulla_id)
    if patrulla is None or not _es_de_la_patrulla(patrulla, usuario):
        return False
    if pagina.oculta and not (usuario.es_educador or pagina.autor_id == usuario.id):
        return False
    return True


def _es_de_la_patrulla(patrulla: Patrulla, usuario: Usuario) -> bool:
    """El mismo criterio que `_patrulla_visible` en los routers."""
    if patrulla.unidad_id != usuario.unidad_id:
        return False
    return usuario.es_educador or patrulla.id == usuario.patrulla_id


# --- Avisar -------------------------------------------------------------------


def avisar(
    sesion: Session,
    usuario: Usuario,
    motivo: str = "",
    entrega: Entrega | None = None,
    pagina: EntradaLibroOro | None = None,
) -> Aviso:
    """Deja constancia de que alguien pide que el equipo mire esto.

    No oculta nada: eso lo decide una persona. Quien ya avisó no vuelve a
    avisar —lo dice la restricción de la tabla y lo dice acá con un mensaje
    entendible, porque un error de base de datos no es una respuesta.
    """
    if entrega is None and pagina is None:
        raise NoSePuede("No hay nada sobre lo que avisar.")

    unidad_id = entrega.asignacion.unidad_id if entrega is not None else _unidad_de_pagina(sesion, pagina)
    ya = sesion.scalar(
        select(Aviso).where(
            Aviso.avisa_id == usuario.id,
            Aviso.entrega_id == (entrega.id if entrega is not None else None),
            Aviso.libro_id == (pagina.id if pagina is not None else None),
        )
    )
    if ya is not None:
        raise NoSePuede("Ya avisaste sobre esto. El equipo lo tiene en su lista.")

    aviso = Aviso(
        unidad_id=unidad_id,
        entrega_id=entrega.id if entrega is not None else None,
        libro_id=pagina.id if pagina is not None else None,
        avisa_id=usuario.id,
        motivo=motivo.strip()[:2000],
    )
    sesion.add(aviso)
    return aviso


def _unidad_de_pagina(sesion: Session, pagina: EntradaLibroOro) -> int:
    patrulla = sesion.get(Patrulla, pagina.patrulla_id)
    if patrulla is None:
        raise NoSePuede("Esa página no existe.")
    return patrulla.unidad_id


def avisados_por(sesion: Session, usuario: Usuario) -> tuple[set[int], set[int]]:
    """Sobre qué ya avisó esta persona: (entregas, páginas de libro).

    Lo usa la pantalla para poner «ya avisaste» en vez de un botón que va a
    fallar. Es una sola consulta y no una por publicación.
    """
    entregas: set[int] = set()
    paginas: set[int] = set()
    for entrega_id, libro_id in sesion.execute(
        select(Aviso.entrega_id, Aviso.libro_id).where(Aviso.avisa_id == usuario.id)
    ):
        if entrega_id is not None:
            entregas.add(entrega_id)
        if libro_id is not None:
            paginas.add(libro_id)
    return entregas, paginas


def avisos_abiertos(sesion: Session, unidad_id: int) -> list[Aviso]:
    """Lo que todavía no miró nadie, lo más viejo primero: es lo que más espera."""
    return list(
        sesion.scalars(
            select(Aviso)
            .where(Aviso.unidad_id == unidad_id, Aviso.atendido_en.is_(None))
            .order_by(Aviso.creado_en)
        )
    )


def atender(avisos: list[Aviso], educador: Usuario, resolucion: str) -> None:
    """Cierra los avisos de una publicación con lo que el equipo terminó haciendo."""
    for aviso in avisos:
        if aviso.atendido:
            continue
        aviso.atendido_en = _ahora()
        aviso.atendido_por_id = educador.id
        aviso.resolucion = resolucion.strip()[:2000]


# --- Bajar y devolver ---------------------------------------------------------


def bajar_entrega(entrega: Entrega, educador: Usuario) -> None:
    """La saca del muro sin tocar la entrega.

    Los puntos quedan: el reto lo hizo. Lo que se baja es la publicación, que es
    otra cosa —y `compartida` tampoco se toca, porque ese interruptor es del
    joven y pisárselo sería contarle una historia falsa sobre su propia entrega.
    """
    entrega.oculta_en = _ahora()
    entrega.oculta_por_id = educador.id


def devolver_entrega(entrega: Entrega) -> None:
    entrega.oculta_en = None
    entrega.oculta_por_id = None


def bajar_pagina(pagina: EntradaLibroOro, educador: Usuario) -> None:
    pagina.oculta_en = _ahora()
    pagina.oculta_por_id = educador.id


def devolver_pagina(pagina: EntradaLibroOro) -> None:
    pagina.oculta_en = None
    pagina.oculta_por_id = None


# --- El feed del equipo -------------------------------------------------------


@dataclass
class Novedad:
    """Una publicación, venga del muro o de un Libro de Oro.

    Las dos cosas son distintas —una entrega tiene puntaje y validación, una
    página de libro no— pero para quien está mirando si hay algo que no debería
    estar publicado son lo mismo: una foto, un nombre y una fecha.
    """

    clase: str  # "muro" | "libro"
    id: int
    cuando: datetime
    titulo: str
    texto: str
    foto: str | None
    autor: Usuario | None
    donde: str
    enlace: str
    oculta: bool
    oculta_por: Usuario | None
    avisos: list[Aviso] = field(default_factory=list)

    @property
    def avisos_abiertos(self) -> list[Aviso]:
        return [a for a in self.avisos if not a.atendido]


def novedades(sesion: Session, unidad_id: int, tope: int = 60) -> list[Novedad]:
    """Todo lo que se publicó en la Unidad, lo último primero.

    Incluye lo que el equipo ya bajó: quien mira tiene que poder ver qué se
    sacó y devolverlo si fue un error. Se piden `tope` de cada lado y se corta
    después de mezclar, que es lo correcto cuando no se sabe de qué lado van a
    venir los más nuevos.
    """
    compartidas = list(
        sesion.scalars(
            select(Entrega)
            .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
            .where(
                Asignacion.unidad_id == unidad_id,
                Entrega.compartida.is_(True),
                Entrega.estado == ESTADO_APROBADA,
            )
            .order_by(_cuando_entrega().desc())
            .limit(tope)
        )
    )
    paginas = list(
        sesion.scalars(
            select(EntradaLibroOro)
            .join(Patrulla, Patrulla.id == EntradaLibroOro.patrulla_id)
            .where(Patrulla.unidad_id == unidad_id)
            .order_by(EntradaLibroOro.creada_en.desc())
            .limit(tope)
        )
    )

    por_entrega: dict[int, list[Aviso]] = {}
    por_pagina: dict[int, list[Aviso]] = {}
    for aviso in sesion.scalars(
        select(Aviso).where(Aviso.unidad_id == unidad_id).order_by(Aviso.creado_en)
    ):
        destino = por_entrega if aviso.entrega_id is not None else por_pagina
        clave = aviso.entrega_id if aviso.entrega_id is not None else aviso.libro_id
        destino.setdefault(clave, []).append(aviso)

    lista = [
        Novedad(
            clase="muro",
            id=e.id,
            cuando=e.compartida_en or e.enviada_en,
            titulo=e.asignacion.reto.titulo,
            texto=e.texto,
            foto=e.archivo_foto,
            autor=e.joven,
            donde="El muro de la Unidad",
            enlace="/muro",
            oculta=e.oculta,
            oculta_por=e.oculta_por,
            avisos=por_entrega.get(e.id, []),
        )
        for e in compartidas
    ] + [
        Novedad(
            clase="libro",
            id=p.id,
            cuando=p.creada_en,
            titulo=p.titulo,
            texto=p.texto,
            foto=p.archivo_foto,
            autor=p.autor,
            donde=f"Libro de Oro · {p.patrulla.nombre}",
            enlace=f"/libro-de-oro/{p.patrulla_id}",
            oculta=p.oculta,
            oculta_por=p.oculta_por,
            avisos=por_pagina.get(p.id, []),
        )
        for p in paginas
    ]

    # Lo avisado y sin atender va arriba de todo, por encima de la fecha: para
    # eso existe el aviso. El resto, lo último primero.
    lista.sort(key=lambda n: (not n.avisos_abiertos, -n.cuando.timestamp()))
    return lista[:tope]


def _cuando_entrega():
    """Cuándo se publicó, con la fecha de entrega como respaldo.

    `compartida_en` es nuevo: lo que ya estaba compartido antes de esta columna
    no lo tiene, y para eso está el `coalesce`.
    """
    return func.coalesce(Entrega.compartida_en, Entrega.enviada_en)


def cuantas_sin_mirar(sesion: Session, unidad_id: int) -> int:
    """Para el número del panel: avisos abiertos, que es lo que pide atención."""
    return sesion.scalar(
        select(func.count(Aviso.id)).where(
            Aviso.unidad_id == unidad_id, Aviso.atendido_en.is_(None)
        )
    ) or 0
