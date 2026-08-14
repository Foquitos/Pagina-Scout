"""Señales: de qué aparato salió cada cosa y cómo entró lo que se escribió.

Este módulo contesta dos preguntas que la aplicación no sabía contestar y que
alguien vino a hacerle:

**«¿Esto lo hizo quien dice?»** Un Guía entrando con la cuenta de cada uno de sus
patrulleros para completarles los retos. Con la sesión sola es indistinguible de
cinco chicos entregando desde su casa, porque la sesión se vacía al salir y no
queda nada que las una. La cookie de `app/aparatos.py` sí queda, y las une.

**«¿Esto lo escribió, o lo pegó?»** Que un relato salga de una IA no se puede
saber, y los detectores que dicen saberlo se equivocan lo suficiente como para
que usarlos signifique acusar en falso a un chico por algo que sí hizo. Lo que
sí se sabe es cómo entró el texto al cuadro: tecleado o pegado. Eso es un hecho
y se guarda como un hecho.

**Ninguna señal decide nada.** Lo más que hace una señal fuerte es que la entrega
no se valide sola y caiga en la lista del educador —que es donde caen las
entregas incompletas desde siempre—, con lo que se vio escrito al lado. Rechazar
sigue siendo de una persona, igual que en `servicios/validacion.py`. Esto no
existe para atrapar a nadie: existe para que una conversación que hoy empieza con
«me parece que vos…» empiece con algo concreto sobre la mesa.

Los umbrales de acá abajo están elegidos para errar por lo bajo. Pegar cuarenta
caracteres es pegar el nombre de un lugar; dos cuentas en un teléfono son dos
hermanos con un solo celular en casa, que es bastante más común que un Guía
haciendo trampa. Se marca fuerte lo que ya no tiene otra lectura razonable, y
todo lo demás se muestra sin marcarlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import tiempo
from app.models import Acceso, Asignacion, Entrega, Rastro, Usuario
from app.servicios.medios import SenalesFoto

# --- Cuánto se mira hacia atrás ------------------------------------------------

# Para juntar entregas del mismo aparato. Un ciclo de programa dura unos tres
# meses: más atrás que eso, un teléfono pudo cambiar de manos y juntaríamos cosas
# que no van juntas.
DIAS_DE_APARATO = 90
# Los ingresos se guardan medio año y después se van solos. Lo que sirve es lo
# reciente; un registro de quién entró desde dónde hace dos años no le hace falta
# a nadie y es lo primero que no habría que tener.
DIAS_DE_ACCESO = 180

# Cuántas cuentas distintas en un mismo aparato dejan de tener otra explicación.
# Dos son dos hermanas con un solo teléfono, que pasa todo el tiempo y no es
# nada. La patrulla entera saliendo del mismo aparato es otra cosa.
CUENTAS_QUE_LLAMAN_LA_ATENCION = 3

# Días entre la fecha del reto y la de la foto a partir de los cuales se dice.
# Una foto del fin de semana pasado subida el martes es lo normal; una de hace
# tres meses es de otra cosa.
DIAS_DE_FOTO_VIEJA = 10

# Caracteres por segundo que ya no son de nadie tecleando. Veinte por segundo son
# unas 240 palabras por minuto sostenidas: si entró así y no se contó como pegue,
# entró por algún camino que el navegador no llamó «pegar».
VELOCIDAD_IMPOSIBLE = 20
# Debajo de esto no se mide velocidad: dos frases se escriben de un tirón.
ESCRITO_PARA_MEDIR_VELOCIDAD = 400


@dataclass(frozen=True)
class ComoSeEscribio:
    """Lo que midió el navegador mientras alguien escribía.

    Llega del formulario, así que se puede falsear con la consola abierta. No
    importa: del otro lado no hay ninguna puerta que esto cierre, y quien sepa
    abrir las herramientas de desarrollo para inflar un contador de tecleo no era
    el problema que vinimos a resolver. Se trata como lo que es —lo que contó el
    navegador— y nunca como una prueba.
    """

    aparato: str = ""
    pegado: int = 0
    tecleado: int = 0
    segundos: int = 0


@dataclass(frozen=True)
class Senal:
    """Algo que se vio, escrito para que lo lea una persona.

    `fuerte` no significa «hizo trampa». Significa que la entrega ya no se valida
    sola: la mira alguien del equipo antes de darla por hecha.
    """

    texto: str
    fuerte: bool = False


# --- Anotar --------------------------------------------------------------------


def registrar_acceso(
    sesion: Session, usuario: Usuario, aparato: str, ip: str, navegador: str
) -> Acceso:
    """Deja constancia de un ingreso, y de paso barre los que ya no sirven."""
    acceso = Acceso(
        usuario_id=usuario.id,
        aparato=aparato[:64],
        ip=(ip or "")[:64],
        navegador=(navegador or "")[:200],
    )
    sesion.add(acceso)
    # Un DELETE con índice sobre una tabla chica cuesta menos que preguntarse
    # cuándo habría que correrlo, así que se corre acá y no hace falta un cron.
    sesion.execute(
        delete(Acceso).where(Acceso.creado_en < tiempo.ahora() - timedelta(days=DIAS_DE_ACCESO))
    )
    return acceso


def anotar(
    sesion: Session, entrega: Entrega, como: ComoSeEscribio, foto: SenalesFoto | None
) -> Rastro:
    """Guarda cómo entró esta entrega. Si se corrige, se pisa lo anterior.

    Se pisa a propósito: el rastro describe **la entrega que está**, no la
    historia de cómo se llegó a ella. Un chico que pegó algo, se arrepintió y lo
    reescribió con sus palabras tiene que quedar con el rastro de lo que
    finalmente entregó, y no arrastrando el del intento que él mismo corrigió.
    """
    rastro = entrega.rastro or Rastro()
    rastro.aparato = (como.aparato or "")[:64]
    rastro.pegado = max(0, como.pegado)
    rastro.tecleado = max(0, como.tecleado)
    rastro.segundos = max(0, como.segundos)

    # Las señales de la foto solo se pisan cuando vino una foto en este envío. Al
    # corregir el texto sin volver a subirla, la que está sigue siendo la que se
    # miró: borrar lo que se sabe de ella sería perder información por nada.
    if foto is not None:
        rastro.hubo_foto = True
        rastro.foto_camara = foto.camara
        rastro.foto_tomada_en = foto.tomada_en
        rastro.foto_software = foto.software
        rastro.foto_generada = foto.generada

    entrega.rastro = rastro
    return rastro


# --- Leer ----------------------------------------------------------------------


def senales(entrega: Entrega, cuentas_en_el_aparato: int = 0) -> list[Senal]:
    """Lo que se vio de esta entrega, escrito para que lo lea un educador.

    Función pura: recibe la cuenta de aparatos ya calculada y no toca la base.
    Así la misma lista sale igual en la pantalla de entregas, donde se pinta de a
    ciento veinte, que al decidir si una entrega espera o no.
    """
    rastro = entrega.rastro
    if rastro is None:
        return []
    return [
        *_del_aparato(entrega, rastro, cuentas_en_el_aparato),
        *_de_la_escritura(rastro),
        *_de_la_foto(entrega, rastro),
    ]


def _del_aparato(entrega: Entrega, rastro: Rastro, cuantas: int) -> list[Senal]:
    if not rastro.aparato or entrega.dictada_por_id is not None or cuantas < 2:
        return []
    return [
        Senal(
            f"del mismo aparato entregaron {cuantas} cuentas distintas",
            fuerte=cuantas >= CUENTAS_QUE_LLAMAN_LA_ATENCION,
        )
    ]


def _de_la_escritura(rastro: Rastro) -> list[Senal]:
    lista: list[Senal] = []
    if rastro.mayormente_pegado:
        lista.append(Senal(f"el relato entró pegado ({rastro.pegado} caracteres)", fuerte=True))
    elif rastro.pegado:
        lista.append(Senal(f"pegó {rastro.pegado} caracteres"))

    # Lo que no se contó como pegue pero entró a una velocidad que no es de nadie
    # tecleando. No se marca fuerte: un teclado de celular que completa palabras
    # enteras infla la cuenta, y ese chico no hizo nada.
    if (
        rastro.escrito >= ESCRITO_PARA_MEDIR_VELOCIDAD
        and rastro.segundos > 0
        and rastro.escrito / rastro.segundos > VELOCIDAD_IMPOSIBLE
    ):
        lista.append(Senal(f"{rastro.escrito} caracteres en {rastro.segundos} segundos"))
    return lista


def _de_la_foto(entrega: Entrega, rastro: Rastro) -> list[Senal]:
    if not rastro.hubo_foto:
        return []

    lista: list[Senal] = []
    if rastro.foto_generada:
        lista.append(Senal("la foto trae el sello de una imagen generada", fuerte=True))
    elif rastro.foto_sin_camara:
        # Sin marcar fuerte, y no es un detalle: WhatsApp le borra los metadatos a
        # todo lo que pasa por él, así que una foto de verdad reenviada llega tan
        # pelada como una inventada, y una captura de pantalla también. Marcar
        # esto fuerte mandaría a revisión a media Unidad todas las semanas.
        lista.append(Senal("la foto no trae datos de cámara"))
    elif rastro.foto_camara:
        lista.append(Senal(f"foto de {rastro.foto_camara}"))

    if rastro.foto_software:
        lista.append(Senal(f"la pasó por {rastro.foto_software}"))

    if rastro.foto_tomada_en is not None:
        dias = (entrega.asignacion.fecha - rastro.foto_tomada_en.date()).days
        if dias > DIAS_DE_FOTO_VIEJA:
            lista.append(Senal(f"la foto es de {dias} días antes del reto"))
    return lista


def cuantos_entregaron_desde(sesion: Session, aparato: str) -> int:
    """Cuántos jóvenes distintos entregaron desde ese aparato en los últimos meses.

    Las entregas dictadas quedan afuera, y es imprescindible que queden: cargar
    lo que hizo un compañero que está sin teléfono es **el uso legítimo** de
    escribir desde el aparato de otro, está firmado con nombre en
    `Entrega.dictada_por_id` y lo habilita el equipo. Contarlas acá convertiría en
    sospechoso justo lo que la aplicación pide hacer (ver `servicios/pausas.py`).
    """
    if not aparato:
        return 0
    return (
        sesion.scalar(
            select(func.count(func.distinct(Entrega.joven_id)))
            .join(Rastro, Rastro.entrega_id == Entrega.id)
            .where(
                Rastro.aparato == aparato,
                Rastro.creado_en >= tiempo.ahora() - timedelta(days=DIAS_DE_APARATO),
                Entrega.dictada_por_id.is_(None),
            )
        )
        or 0
    )


def hay_que_mirarla(sesion: Session, entrega: Entrega) -> list[Senal]:
    """Las señales fuertes de una entrega recién recibida. Vacío = se valida sola.

    Es el camino de una entrega sola: una consulta chica en vez del mapa de toda
    la Unidad. La misma función de señales que la pantalla del equipo, para que no
    puedan decir cosas distintas.
    """
    if entrega.rastro is None:
        return []
    cuantas = cuantos_entregaron_desde(sesion, entrega.rastro.aparato)
    return [s for s in senales(entrega, cuantas) if s.fuerte]


def por_entrega(sesion: Session, unidad_id: int, entregas: list[Entrega]) -> dict[int, list[Senal]]:
    """Las señales de un montón de entregas, con una sola consulta para todas.

    La pantalla del equipo muestra ciento veinte por página: preguntar por cada
    una serían ciento veinte viajes a la base para pintar una línea de texto.
    """
    if not entregas:
        return {}
    cuentas = _cuentas_por_aparato(sesion, unidad_id)
    return {
        e.id: lista
        for e in entregas
        if (lista := senales(e, cuentas.get(e.rastro.aparato, 0) if e.rastro else 0))
    }


def _cuentas_por_aparato(sesion: Session, unidad_id: int) -> dict[str, int]:
    """Cuántos jóvenes distintos entregó cada aparato, para toda la Unidad."""
    filas = sesion.execute(
        select(Rastro.aparato, func.count(func.distinct(Entrega.joven_id)))
        .join(Entrega, Entrega.id == Rastro.entrega_id)
        .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
        .where(
            Asignacion.unidad_id == unidad_id,
            Rastro.aparato != "",
            Rastro.creado_en >= tiempo.ahora() - timedelta(days=DIAS_DE_APARATO),
            Entrega.dictada_por_id.is_(None),
        )
        .group_by(Rastro.aparato)
    )
    return {aparato: cuantos for aparato, cuantos in filas}


# --- La pantalla del equipo ----------------------------------------------------


@dataclass
class AparatoCompartido:
    """Un aparato del que se movió más de una cuenta.

    Se guardan las dos listas por separado y hacen falta las dos: alguien puede
    entrar a una cuenta ajena y no entregar nada —mirarla, cambiarle algo— y eso
    también hay que poder verlo.
    """

    aparato: str
    entregaron: list[Usuario] = field(default_factory=list)
    entraron: list[Usuario] = field(default_factory=list)
    ultimo: datetime | None = None

    @property
    def todos(self) -> list[Usuario]:
        vistos: dict[int, Usuario] = {}
        for usuario in self.entregaron + self.entraron:
            vistos.setdefault(usuario.id, usuario)
        return sorted(vistos.values(), key=lambda u: u.nombre)

    @property
    def cuantos(self) -> int:
        return len(self.todos)

    @property
    def llama_la_atencion(self) -> bool:
        return self.cuantos >= CUENTAS_QUE_LLAMAN_LA_ATENCION


def compartidos(sesion: Session, unidad_id: int) -> list[AparatoCompartido]:
    """Los aparatos desde los que se movió más de una cuenta de la Unidad.

    Los que llaman la atención primero y, dentro de eso, los más recientes. Un
    aparato con una sola cuenta no aparece: ese es el caso de todo el mundo.
    """
    desde = tiempo.ahora() - timedelta(days=DIAS_DE_APARATO)
    entregaron: dict[str, dict[int, Usuario]] = {}
    entraron: dict[str, dict[int, Usuario]] = {}
    ultimo: dict[str, datetime] = {}

    def anotar_en(donde: dict, aparato: str, quien: Usuario, cuando: datetime) -> None:
        donde.setdefault(aparato, {})[quien.id] = quien
        if cuando is not None and (aparato not in ultimo or cuando > ultimo[aparato]):
            ultimo[aparato] = cuando

    for aparato, joven, cuando in sesion.execute(
        select(Rastro.aparato, Usuario, Rastro.creado_en)
        .join(Entrega, Entrega.id == Rastro.entrega_id)
        .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
        .join(Usuario, Usuario.id == Entrega.joven_id)
        .where(
            Asignacion.unidad_id == unidad_id,
            Rastro.aparato != "",
            Rastro.creado_en >= desde,
            Entrega.dictada_por_id.is_(None),
        )
    ):
        anotar_en(entregaron, aparato, joven, cuando)

    for aparato, quien, cuando in sesion.execute(
        select(Acceso.aparato, Usuario, Acceso.creado_en)
        .join(Usuario, Usuario.id == Acceso.usuario_id)
        .where(Usuario.unidad_id == unidad_id, Acceso.aparato != "", Acceso.creado_en >= desde)
    ):
        anotar_en(entraron, aparato, quien, cuando)

    lista = [
        AparatoCompartido(
            aparato=aparato,
            entregaron=sorted(entregaron.get(aparato, {}).values(), key=lambda u: u.nombre),
            entraron=sorted(entraron.get(aparato, {}).values(), key=lambda u: u.nombre),
            ultimo=ultimo.get(aparato),
        )
        for aparato in set(entregaron) | set(entraron)
    ]
    return sorted(
        (a for a in lista if a.cuantos > 1),
        key=lambda a: (not a.llama_la_atencion, -(a.ultimo.timestamp() if a.ultimo else 0)),
    )


def cuantos_llaman_la_atencion(sesion: Session, unidad_id: int) -> int:
    """El número del panel: aparatos con tres cuentas distintas o más."""
    return sum(1 for a in compartidos(sesion, unidad_id) if a.llama_la_atencion)
