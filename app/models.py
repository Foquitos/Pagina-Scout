"""Modelo de datos.

El vocabulario sigue el del Método Scout (Rama Scouts / Unidad) para que el
código se lea igual que la guía: Unidad, Patrulla, competencia, desafío, etapa.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Lo que queda guardado en cada columna de fecha y hora: el instante en UTC. La
# traducción a la hora de la Unidad es de la pantalla; ver `app/tiempo.py`.
from app.tiempo import ahora as _ahora

# --- Vocabularios ------------------------------------------------------------

ROL_JOVEN = "joven"
ROL_EDUCADOR = "educador"
ROLES = (ROL_JOVEN, ROL_EDUCADOR)

# Etapas de progresión personal de la Rama Scouts (cap. 9 de la guía).
ETAPAS = ("pistas", "senda", "rumbo", "travesia")
ETAPAS_NOMBRE = {
    "pistas": "Pistas",
    "senda": "Senda",
    "rumbo": "Rumbo",
    "travesia": "Travesía",
}

ALCANCE_UNIDAD = "unidad"
ALCANCE_PATRULLA = "patrulla"
ALCANCE_JOVEN = "joven"

ESTADO_PENDIENTE = "pendiente"
ESTADO_REVISION = "requiere_revision"
ESTADO_APROBADA = "aprobada"
ESTADO_RECHAZADA = "rechazada"

TIPO_CARTA = "carta"
TIPO_PERSONALIZADO = "personalizado"

# Tipos de desafío dentro de una carta. Los requeridos son los mínimos
# indispensables para desarrollar la competencia; los opcionales enriquecen y
# pueden reemplazar a un requerido conversándolo con el educador. Las
# especialidades y roles de patrulla cuentan como opcionales (cap. 9).
DESAFIO_REQUERIDO = "requerido"
DESAFIO_OPCIONAL = "opcional"
DESAFIO_ESPECIALIDAD = "especialidad"
DESAFIO_TIPOS_NOMBRE = {
    DESAFIO_REQUERIDO: "Requerido",
    DESAFIO_OPCIONAL: "Opcional",
    DESAFIO_ESPECIALIDAD: "Especialidad o rol",
}

# Cargos de patrulla (cap. 4). El catálogo es de cada Unidad porque la guía dice
# que «pueden variar en cantidad y en denominación, de acuerdo con las
# costumbres de las Unidades». Estos son el punto de partida, no la lista.
CARGOS_INICIALES = (
    ("Guía", "Coordina la patrulla y la representa en el Consejo de Unidad."),
    ("Subguía", "Acompaña al Guía y lo reemplaza cuando no está."),
    ("Secretario/a", "Escribe las actas del Consejo y cuida el Libro de Oro."),
    ("Tesorero/a", "Lleva la caja de la patrulla y rinde cuentas."),
    ("Cocinero/a", "Arma los menús y la cocina del campamento."),
    ("Intendente", "Cuida el material, las carpas y el equipo."),
    ("Enfermero/a", "Tiene el botiquín al día y sabe usarlo."),
    ("Animador/a", "Junta los juegos, las canciones y el grito."),
)

# Oportunidades de aprendizaje del calendario (cap. 7 y 8). Las tres primeras
# son las variables —las que eligen las patrullas y la Asamblea—; campamento y
# celebración son de las fijas, que también van al calendario del ciclo.
CLASE_ACTIVIDAD = "actividad"
CLASE_PROYECTO = "proyecto"
CLASE_DESCUBIERTA = "descubierta"
CLASE_CAMPAMENTO = "campamento"
CLASE_CELEBRACION = "celebracion"
CLASES_ACTIVIDAD = (
    CLASE_ACTIVIDAD,
    CLASE_PROYECTO,
    CLASE_DESCUBIERTA,
    CLASE_CAMPAMENTO,
    CLASE_CELEBRACION,
)
CLASES_ACTIVIDAD_NOMBRE = {
    CLASE_ACTIVIDAD: "Actividad",
    CLASE_PROYECTO: "Proyecto",
    CLASE_DESCUBIERTA: "Descubierta",
    CLASE_CAMPAMENTO: "Campamento",
    CLASE_CELEBRACION: "Celebración",
}
CLASES_ACTIVIDAD_ICONO = {
    CLASE_ACTIVIDAD: "🎪",
    CLASE_PROYECTO: "🛠️",
    CLASE_DESCUBIERTA: "🔎",
    CLASE_CAMPAMENTO: "⛺",
    CLASE_CELEBRACION: "🎉",
}

# Una idea propuesta por un joven espera a la Asamblea, que es presencial. La
# aplicación no vota: junta las propuestas, deja marcar cuáles se ven posibles y
# guarda las que salieron elegidas cuando la Unidad ya lo decidió en persona.
IDEA_PROPUESTA = "propuesta"
IDEA_POSIBLE = "posible"
IDEA_ELEGIDA = "elegida"
IDEA_GUARDADA = "guardada"
IDEAS_ESTADO = (IDEA_PROPUESTA, IDEA_POSIBLE, IDEA_ELEGIDA, IDEA_GUARDADA)
IDEAS_ESTADO_NOMBRE = {
    IDEA_PROPUESTA: "Propuesta",
    IDEA_POSIBLE: "Se puede hacer",
    IDEA_ELEGIDA: "Elegida en la Asamblea",
    IDEA_GUARDADA: "Guardada para después",
}

# Las tres fases de una especialidad (cap. 9), con el verbo que usa la guía.
FASE_EXPLORACION = "exploracion"
FASE_TALLER = "taller"
FASE_DESAFIO = "desafio"
FASES_ESPECIALIDAD = (FASE_EXPLORACION, FASE_TALLER, FASE_DESAFIO)
FASES_ESPECIALIDAD_NOMBRE = {
    FASE_EXPLORACION: "Exploración (conocer)",
    FASE_TALLER: "Taller (hacer)",
    FASE_DESAFIO: "Desafío (servir)",
}


# --- Organización ------------------------------------------------------------


class Unidad(Base):
    __tablename__ = "unidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    grupo: Mapped[str] = mapped_column(String(120), default="")

    patrullas: Mapped[list["Patrulla"]] = relationship(back_populates="unidad")
    miembros: Mapped[list["Usuario"]] = relationship(back_populates="unidad")


class Patrulla(Base):
    """Un grupo de amigas y amigos, con nombre propio (cap. 4).

    Los campos de identidad —grito, emblema, historia, banderín— no son adorno.
    La guía dice que cada patrulla «posee una identidad propia» y que integrarse
    a ella es tanto lo social como lo simbólico: reconocerse en el nombre, el
    lema y los colores. Que eso tenga lugar en la aplicación es parte del método,
    no decoración.
    """

    __tablename__ = "patrullas"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"))
    nombre: Mapped[str] = mapped_column(String(80))
    lema: Mapped[str] = mapped_column(String(200), default="")
    color: Mapped[str] = mapped_column(String(20), default="#3E8E5A")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)

    grito: Mapped[str] = mapped_column(Text, default="")
    emblema: Mapped[str] = mapped_column(String(10), default="")
    historia: Mapped[str] = mapped_column(Text, default="")
    archivo_banderin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fundada_en: Mapped[date | None] = mapped_column(Date, nullable=True)

    unidad: Mapped[Unidad] = relationship(back_populates="patrullas")
    integrantes: Mapped[list["Usuario"]] = relationship(back_populates="patrulla")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    hash_clave: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20), default=ROL_JOVEN)
    unidad_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"), nullable=True)
    patrulla_id: Mapped[int | None] = mapped_column(ForeignKey("patrullas.id"), nullable=True)
    etapa: Mapped[str] = mapped_column(String(20), default="pistas")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Opcional, y que siga siéndolo. Es el único dato personal además del nombre
    # que la aplicación guarda, así que no se pide para poder usar la cuenta:
    # quien no lo quiera dar, no lo da, y todo lo demás funciona igual. La edad
    # nunca se guarda calculada —se saca de acá cuando hace falta— porque un
    # número que envejece solo en la base es un número que en algún momento miente.
    nacimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Toda cuenta nace con su propio nombre de usuario como contraseña, así que
    # hasta que la persona ponga una suya no sirve para nada más que para
    # cambiarla: con esto encendido, la única página que abre es /clave. Ver
    # servicios/cuentas.py.
    debe_cambiar_clave: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    unidad: Mapped[Unidad | None] = relationship(back_populates="miembros")
    patrulla: Mapped[Patrulla | None] = relationship(back_populates="integrantes")

    @property
    def es_educador(self) -> bool:
        return self.rol == ROL_EDUCADOR

    @property
    def etapa_nombre(self) -> str:
        return ETAPAS_NOMBRE.get(self.etapa, self.etapa)

    def edad_al(self, dia: date) -> int | None:
        """Años cumplidos a esa fecha. `None` si no cargó el cumpleaños.

        La resta de años menos uno si todavía no llegó el día: comparar tuplas
        `(mes, día)` resuelve de una el caso del 29 de febrero, que restando
        fechas hay que pensarlo aparte.
        """
        if self.nacimiento is None:
            return None
        cumplio_ya = (dia.month, dia.day) >= (self.nacimiento.month, self.nacimiento.day)
        return dia.year - self.nacimiento.year - (0 if cumplio_ya else 1)


# --- Cartas de Exploración ---------------------------------------------------


class Area(Base):
    """Una de las cuatro áreas de desarrollo del programa."""

    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nombre: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(20))
    icono: Mapped[str] = mapped_column(String(10), default="")
    descripcion: Mapped[str] = mapped_column(Text, default="")

    competencias: Mapped[list["Competencia"]] = relationship(back_populates="area")


class Competencia(Base):
    """Una carta de exploración: competencia educativa + sus desafíos."""

    __tablename__ = "competencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, unique=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    titulo: Mapped[str] = mapped_column(Text)

    area: Mapped[Area] = relationship(back_populates="competencias")
    desafios: Mapped[list["Desafio"]] = relationship(
        back_populates="competencia", order_by="Desafio.orden"
    )


class Desafio(Base):
    __tablename__ = "desafios"

    id: Mapped[int] = mapped_column(primary_key=True)
    competencia_id: Mapped[int] = mapped_column(ForeignKey("competencias.id"))
    orden: Mapped[int] = mapped_column(Integer)
    texto: Mapped[str] = mapped_column(Text)
    # requerido | opcional | especialidad | None (todavía sin clasificar)
    tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)

    @property
    def tipo_nombre(self) -> str | None:
        return DESAFIO_TIPOS_NOMBRE.get(self.tipo) if self.tipo else None

    competencia: Mapped[Competencia] = relationship(back_populates="desafios")


class CompetenciaElegida(Base):
    """Las 12 a 14 cartas que cada joven elige para su etapa actual.

    La elige el joven y **la cierra el joven**, escribiendo su autoevaluación.
    El capítulo 9 no deja lugar a dudas sobre de quién es esa lapicera: «la joven
    o el joven son los principales protagonistas de la evaluación de la
    progresión personal» y, si el educador no coincide, «siempre primará la
    autoevaluación». Por eso `lograda_por_id` es quien la cerró —puede ser el
    propio joven— y el acuerdo del equipo se anota aparte, en `acordada`: una
    carta cerrada cuenta desde que la cerró su dueño, y lo que falta después no
    es permiso sino conversación.

    `con_pendientes` marca las que se cerraron sin todos los requeridos —la guía
    lo permite, un desafío opcional puede reemplazar a uno requerido—, pero no se
    cierra en silencio.
    """

    __tablename__ = "competencias_elegidas"
    __table_args__ = (UniqueConstraint("joven_id", "competencia_id", "etapa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    competencia_id: Mapped[int] = mapped_column(ForeignKey("competencias.id"))
    etapa: Mapped[str] = mapped_column(String(20))
    lograda: Mapped[bool] = mapped_column(Boolean, default=False)
    elegida_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    lograda_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lograda_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    con_pendientes: Mapped[bool] = mapped_column(Boolean, default=False)
    nota_cierre: Mapped[str] = mapped_column(Text, default="")

    # Lo que el joven escribe al cerrar la carta, con las preguntas del cap. 9.
    autoevaluacion: Mapped[str] = mapped_column(Text, default="")
    # El equipo de educadores coincide. No habilita nada: deja constancia de que
    # la conversación pasó.
    acordada: Mapped[bool] = mapped_column(Boolean, default=False)
    acordada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acordada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    competencia: Mapped[Competencia] = relationship()
    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    lograda_por: Mapped[Usuario | None] = relationship(foreign_keys=[lograda_por_id])
    acordada_por: Mapped[Usuario | None] = relationship(foreign_keys=[acordada_por_id])

    @property
    def cerrada_por_el_joven(self) -> bool:
        return self.lograda and self.lograda_por_id == self.joven_id

    @property
    def espera_conversacion(self) -> bool:
        """Cerrada por su dueño y todavía sin el acuerdo del equipo."""
        return self.lograda and not self.acordada


class AvanceDesafio(Base):
    """Lo que el joven marcó como hecho dentro de una carta, y lo que escribió.

    Va por etapa y a propósito no cuelga de `CompetenciaElegida`: si saca una
    carta de su elección y más adelante la vuelve a poner, su trabajo sigue ahí.

    El comentario es de la persona, no del educador. Lo leen su patrulla y el
    equipo de educadores (cap. 9: la evaluación se conversa, no se puntúa).
    """

    __tablename__ = "avances_desafio"
    __table_args__ = (UniqueConstraint("joven_id", "desafio_id", "etapa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    desafio_id: Mapped[int] = mapped_column(ForeignKey("desafios.id"))
    etapa: Mapped[str] = mapped_column(String(20))
    hecho: Mapped[bool] = mapped_column(Boolean, default=False)
    comentario: Mapped[str] = mapped_column(Text, default="")
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, default=_ahora, onupdate=_ahora
    )

    desafio: Mapped[Desafio] = relationship()
    joven: Mapped[Usuario] = relationship()


class CambioEtapa(Base):
    """Cada paso de etapa, con quién lo decidió y cómo venían las cartas.

    La etapa la cambia siempre un educador (cap. 9: el paso de etapa lo define
    el equipo con el joven, no un contador). Se guarda la foto del momento
    —cuántas cartas tenía elegidas y cuántas logradas— porque las cartas viven
    atadas a su etapa: después del cambio, la etapa nueva arranca sin ninguna y
    ese número ya no se puede recalcular.
    """

    __tablename__ = "cambios_etapa"

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    etapa_anterior: Mapped[str] = mapped_column(String(20))
    etapa_nueva: Mapped[str] = mapped_column(String(20))
    educador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    cartas_elegidas: Mapped[int] = mapped_column(Integer, default=0)
    cartas_logradas: Mapped[int] = mapped_column(Integer, default=0)
    # True si se cambió sin tener las cartas de la etapa logradas.
    con_pendientes: Mapped[bool] = mapped_column(Boolean, default=False)
    nota: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    educador: Mapped[Usuario | None] = relationship(foreign_keys=[educador_id])

    @property
    def anterior_nombre(self) -> str:
        return ETAPAS_NOMBRE.get(self.etapa_anterior, self.etapa_anterior)

    @property
    def nueva_nombre(self) -> str:
        return ETAPAS_NOMBRE.get(self.etapa_nueva, self.etapa_nueva)


# --- Retos y entregas --------------------------------------------------------


class Reto(Base):
    """Una propuesta de acción concreta, derivada de una carta o inventada."""

    __tablename__ = "retos"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200))
    consigna: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), default=TIPO_CARTA)
    desafio_id: Mapped[int | None] = mapped_column(ForeignKey("desafios.id"), nullable=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    puntaje: Mapped[int] = mapped_column(Integer, default=10)
    pide_texto: Mapped[bool] = mapped_column(Boolean, default=True)
    pide_foto: Mapped[bool] = mapped_column(Boolean, default=False)
    unidad_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"), nullable=True)
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    desafio: Mapped[Desafio | None] = relationship()
    area: Mapped[Area | None] = relationship()
    creado_por: Mapped[Usuario | None] = relationship()


class Asignacion(Base):
    """Un reto puesto en juego para una fecha y un alcance determinados."""

    __tablename__ = "asignaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    reto_id: Mapped[int] = mapped_column(ForeignKey("retos.id"))
    fecha: Mapped[date] = mapped_column(Date, index=True)
    alcance: Mapped[str] = mapped_column(String(20), default=ALCANCE_UNIDAD)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"))
    patrulla_id: Mapped[int | None] = mapped_column(ForeignKey("patrullas.id"), nullable=True)
    joven_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    asignado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    automatica: Mapped[bool] = mapped_column(Boolean, default=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    reto: Mapped[Reto] = relationship()
    patrulla: Mapped[Patrulla | None] = relationship(foreign_keys=[patrulla_id])
    joven: Mapped[Usuario | None] = relationship(foreign_keys=[joven_id])
    entregas: Mapped[list["Entrega"]] = relationship(back_populates="asignacion")


class Entrega(Base):
    """La evidencia que sube un joven y su recorrido de validación."""

    __tablename__ = "entregas"
    __table_args__ = (UniqueConstraint("asignacion_id", "joven_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asignacion_id: Mapped[int] = mapped_column(ForeignKey("asignaciones.id"))
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # Copia de la patrulla al momento de entregar: si el joven cambia de
    # patrulla más adelante, los puntos quedan donde se ganaron.
    patrulla_id: Mapped[int | None] = mapped_column(ForeignKey("patrullas.id"), nullable=True)

    texto: Mapped[str] = mapped_column(Text, default="")
    archivo_foto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enviada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    # Compartida en el muro de la Unidad. Lo decide quien la escribió, y por eso
    # arranca apagada: mostrar lo que hizo un chico sin preguntarle no se hace.
    compartida: Mapped[bool] = mapped_column(Boolean, default=False)
    # Cuándo se publicó, que no es cuándo se entregó: alguien puede compartir en
    # noviembre algo que entregó en marzo. El feed del equipo se ordena por esto,
    # o lo nuevo aparecería enterrado ocho meses atrás.
    compartida_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # El equipo la bajó del muro. Es una segunda llave, no la misma: `compartida`
    # sigue siendo del autor y nadie se la toca, pero mientras esto tenga fecha
    # no se ve. Que sean dos evita la discusión de quién pisó a quién.
    oculta_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    oculta_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    estado: Mapped[str] = mapped_column(String(20), default=ESTADO_PENDIENTE)
    devolucion: Mapped[str] = mapped_column(Text, default="")
    # Quién escribió la devolución que se está mostrando, y cuándo. No alcanza
    # con `validada_por`: una entrega que se aprobó sola puede recibir después
    # el comentario de un educador —«esto estuvo muy bien»— sin que eso cambie
    # quién la validó ni cuándo. Vacío significa que la escribió el validador
    # automático, y la pantalla del joven lo dice así en vez de firmarla como
    # si viniera de una persona.
    devolucion_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    devolucion_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    validada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    validador: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    puntaje_otorgado: Mapped[int] = mapped_column(Integer, default=0)

    # Quién la escribió, cuando no la escribió su dueño. Un chico sin teléfono
    # le cuenta a un educador o a alguien de su patrulla lo que hizo y esa
    # persona lo carga acá (ver `PausaSinTelefono`). El reto sigue siendo suyo
    # —`joven_id` no se mueve, los puntos van a su patrulla y le cuenta para su
    # progresión—; esto es la firma de quien tipeó, y se muestra siempre: a él,
    # a su patrulla y al equipo. Una entrega escrita por otro que no dijera
    # quién fue sería exactamente lo que no queremos.
    dictada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    asignacion: Mapped[Asignacion] = relationship(back_populates="entregas")
    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    patrulla: Mapped[Patrulla | None] = relationship(foreign_keys=[patrulla_id])
    validada_por: Mapped[Usuario | None] = relationship(foreign_keys=[validada_por_id])
    devolucion_por: Mapped[Usuario | None] = relationship(foreign_keys=[devolucion_por_id])
    oculta_por: Mapped[Usuario | None] = relationship(foreign_keys=[oculta_por_id])
    dictada_por: Mapped[Usuario | None] = relationship(foreign_keys=[dictada_por_id])
    # Un aviso señala una publicación: si la publicación se va —sacar el reto de
    # la agenda se lleva sus entregas—, el aviso se va con ella. Sin esto la
    # clave foránea impide el borrado y sale un 500 en una pantalla del educador.
    avisos: Mapped[list["Aviso"]] = relationship(
        back_populates="entrega", cascade="all, delete-orphan"
    )
    # Cómo entró esta entrega. Se va con ella por la misma razón que los avisos.
    rastro: Mapped["Rastro | None"] = relationship(
        back_populates="entrega", cascade="all, delete-orphan", uselist=False
    )

    @property
    def devolucion_firmada_por(self) -> Usuario | None:
        """Quién escribió la devolución que se ve, o None si la escribió sola.

        `devolucion_por` es lo que se anota desde que se puede comentar una
        entrega sin decidir nada sobre ella. Para lo escrito antes hay que caer
        en `validada_por`: hasta entonces una devolución solo podía llegar
        pegada a una decisión de un educador, así que quien decidió es quien
        escribió. Sin esa segunda vuelta, todo lo que ya estaba escrito
        aparecería como automático, que es peor que no firmarlo.

        Esa vuelta pide mirar `validador`: si la última palabra la tuvo un
        validador automático —porque el joven corrigió su entrega después—, la
        devolución que se está viendo es la de la máquina, y ahí firmar con el
        nombre del educador que decidió antes sería ponerle en la boca algo que
        no dijo.
        """
        if self.devolucion_por is not None:
            return self.devolucion_por
        return self.validada_por if self.validador == "educador" else None

    @property
    def oculta(self) -> bool:
        return self.oculta_en is not None

    @property
    def dictada(self) -> bool:
        return self.dictada_por_id is not None

    @property
    def en_el_muro(self) -> bool:
        """Las tres condiciones juntas. La consulta del muro dice lo mismo en SQL."""
        return self.compartida and self.estado == ESTADO_APROBADA and not self.oculta


class PausaSinTelefono(Base):
    """El tramo en que alguien no puede entregar por su cuenta.

    Se le rompió el celular, se lo sacaron en casa, lo comparte con una hermana
    que lo necesita para la escuela. Ninguna de esas cosas la decidió él y sin
    embargo las pagaba su patrulla: el tablero divide los puntos por la cantidad
    de integrantes, así que alguien que no puede entregar arrastra hacia abajo el
    promedio de los otros cuatro. El capítulo 4 pide justo lo contrario —«el
    propósito principal del sistema de patrullas es asignar verdadera
    responsabilidad al mayor número posible de jóvenes»—, y un equipo no le pasa
    la factura al que se quedó sin herramientas.

    Mientras la pausa está vigente pasan dos cosas, y hacen falta las dos:

    - **No divide.** Los puntos que esa persona hizo se quedan en el total de su
      patrulla —los hizo—, pero su cabeza sale del divisor del promedio. El
      tablero lo dice en voz alta («entre 4, 1 en pausa»): no hay número que se
      arregle por detrás.
    - **Se puede entregar por él.** Un educador o alguien de su misma patrulla
      carga lo que le contó. Queda a su nombre y firmado por quien lo escribió,
      en `Entrega.dictada_por_id`.

    `vuelve_el` es **el día que lo tiene de vuelta**, no el último día sin él: la
    pausa vale hasta el día anterior. Se llama así y no `hasta` justamente para
    que no haya que preguntarse si el borde entra o no entra, que es el error que
    después nadie encuentra. Vacío significa «sigue, y no se sabe hasta cuándo».

    Se puede dejar puesto desde el principio —«lo tiene de vuelta el 20»— y
    entonces la pausa se vence sola. Es lo que conviene siempre que se sepa: un
    chico que recuperó el teléfono hace un mes y nadie se acordó de cerrar nada
    no puede quedar fuera del divisor para siempre. Cerrarla a mano es ponerle
    `vuelve_el` = hoy, y desde hoy mismo vuelve a contar.

    **La abre y la cierra un educador.** No es desconfianza: es que sacar a
    alguien del divisor mueve el tablero de toda la Unidad, y en esta aplicación
    lo que mueve algo de otros lo firma alguien con nombre.

    **El motivo lo lee solo el equipo.** A la patrulla y al tablero les alcanza
    con «está sin teléfono»; «lo castigaron en casa» es de esa familia y no de
    treinta personas. Es la misma regla del cumpleaños: se muestra la mitad que
    hace falta y no el dato entero.
    """

    __tablename__ = "pausas_sin_telefono"

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    # Para el equipo, y para acordarse en dos semanas de por qué esto estaba
    # abierto. Puede venir vacío: es peor que no se registre la pausa a que se
    # registre sin explicación.
    motivo: Mapped[str] = mapped_column(Text, default="")
    desde: Mapped[date] = mapped_column(Date, index=True)
    # El día que lo tiene de vuelta: ese día ya cuenta. Vacío es «sigue».
    vuelve_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    abierta_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    cerrada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    abierta_por: Mapped[Usuario | None] = relationship(foreign_keys=[abierta_por_id])
    cerrada_por: Mapped[Usuario | None] = relationship(foreign_keys=[cerrada_por_id])

    def vigente_en(self, dia: date) -> bool:
        return self.desde <= dia and (self.vuelve_el is None or dia < self.vuelve_el)

    @property
    def sin_fecha_de_vuelta(self) -> bool:
        return self.vuelve_el is None


class EntradaBitacora(Base):
    """Bitácora de Aventura: el registro personal de cada joven."""

    __tablename__ = "bitacora"

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    entrega_id: Mapped[int | None] = mapped_column(ForeignKey("entregas.id"), nullable=True)
    titulo: Mapped[str] = mapped_column(String(200), default="")
    texto: Mapped[str] = mapped_column(Text)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    joven: Mapped[Usuario] = relationship()


class Especialidad(Base):
    """Una especialidad que un joven pidió y está desarrollando (cap. 9).

    Dos cosas que parecen contradecirse y no:

    **La pide el joven, y pide la que quiere.** «Tanto la decisión de desarrollar
    una especialidad como la elección del tema específico son personales y
    voluntarias de cada joven», y el único requisito es que lo desee. No hay
    catálogo del que elegir: si a alguien le interesa la apicultura, escribe
    apicultura. Un menú cerrado convertiría en «no se puede» todo lo que a los
    adultos no se les ocurrió.

    **Pero el recorrido lo prepara el equipo.** La guía les encarga conocer el
    tema, contactar a la persona experta e informarle el sentido de esto, y
    pensar qué se espera en cada fase. Por eso pedirla no es empezarla: primero
    hay una respuesta del equipo, que es `preparada_en` y los tres `pide_*`.

    De ahí los tres estados: **pedida** (el joven avisó), **en marcha** (el
    equipo la preparó) y **lograda** (el equipo la dio por concluida). Los
    requisitos «son solo una referencia, pudiendo ser modificadas, teniendo en
    cuenta las particularidades de cada joven»: por eso son texto libre y se
    escriben para *esta* persona, no para todas.

    No se puntúa: no tiene nada que ver con el reto del día ni con el tablero.
    """

    __tablename__ = "especialidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    # Lo escribe el joven: es lo que quiere aprender, con sus palabras.
    nombre: Mapped[str] = mapped_column(String(120))
    icono: Mapped[str] = mapped_column(String(10), default="⭐")
    # Por qué la pide. Es lo primero que el equipo lee para poder acompañarla.
    motivo: Mapped[str] = mapped_column(Text, default="")

    # --- lo que escribe el equipo al prepararla ---
    # La persona experta que acompaña. La guía insiste en que exista y en que no
    # tiene por qué ser del equipo: puede ser la abuela que cocina.
    experto: Mapped[str] = mapped_column(String(120), default="")
    pide_exploracion: Mapped[str] = mapped_column(Text, default="")
    pide_taller: Mapped[str] = mapped_column(Text, default="")
    pide_desafio: Mapped[str] = mapped_column(Text, default="")
    preparada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    preparada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )

    # --- lo que escribe el joven mientras la hace ---
    fase: Mapped[str] = mapped_column(String(20), default=FASE_EXPLORACION)
    exploracion: Mapped[str] = mapped_column(Text, default="")
    taller: Mapped[str] = mapped_column(Text, default="")
    desafio: Mapped[str] = mapped_column(Text, default="")

    lograda: Mapped[bool] = mapped_column(Boolean, default=False)
    lograda_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lograda_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    nota_cierre: Mapped[str] = mapped_column(Text, default="")
    pedida_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    preparada_por: Mapped[Usuario | None] = relationship(foreign_keys=[preparada_por_id])
    lograda_por: Mapped[Usuario | None] = relationship(foreign_keys=[lograda_por_id])

    @property
    def preparada(self) -> bool:
        return self.preparada_en is not None

    @property
    def estado(self) -> str:
        if self.lograda:
            return "lograda"
        return "en_marcha" if self.preparada else "pedida"

    @property
    def fase_nombre(self) -> str:
        return FASES_ESPECIALIDAD_NOMBRE.get(self.fase, self.fase)

    @property
    def pide(self) -> dict[str, str]:
        return {
            FASE_EXPLORACION: self.pide_exploracion,
            FASE_TALLER: self.pide_taller,
            FASE_DESAFIO: self.pide_desafio,
        }

    @property
    def escrito(self) -> dict[str, str]:
        return {
            FASE_EXPLORACION: self.exploracion,
            FASE_TALLER: self.taller,
            FASE_DESAFIO: self.desafio,
        }


# --- La vida de la patrulla (cap. 4) -----------------------------------------


class Cargo(Base):
    """Un rol de patrulla dentro del catálogo de la Unidad.

    «El propósito principal del sistema de patrullas es asignar verdadera
    responsabilidad al mayor número posible de jóvenes» (Baden-Powell, 1919,
    citado en el cap. 4). El catálogo es por Unidad porque los nombres cambian
    de una a otra, y se puede desactivar pero no borrar: los períodos ya
    cumplidos cuelgan de él y son parte de la progresión de alguien.
    """

    __tablename__ = "cargos"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(80))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    orden: Mapped[int] = mapped_column(Integer, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class PeriodoCargo(Base):
    """Quién tuvo qué cargo, desde cuándo, y cómo lo evaluó su Consejo.

    La guía pide expresamente que no se fijen períodos rígidos: «dejando que la
    evaluación interna de la patrulla regule este aspecto». Por eso `hasta` nace
    vacío y lo cierra el Consejo de Patrulla cuando le parece, no un calendario.

    `cumplido` en `None` significa «todavía no se evaluó», que no es lo mismo que
    «no lo cumplió». Los requisitos de etapa cuentan solo los `True`.
    """

    __tablename__ = "periodos_cargo"

    id: Mapped[int] = mapped_column(primary_key=True)
    cargo_id: Mapped[int] = mapped_column(ForeignKey("cargos.id"))
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    patrulla_id: Mapped[int | None] = mapped_column(ForeignKey("patrullas.id"), nullable=True)
    desde: Mapped[date] = mapped_column(Date)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    cumplido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nota: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    cargo: Mapped[Cargo] = relationship()
    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    patrulla: Mapped[Patrulla | None] = relationship()

    @property
    def abierto(self) -> bool:
        return self.hasta is None


class ConsejoPatrulla(Base):
    """El acta de un Consejo de Patrulla (cap. 4).

    Es «la instancia formal de la toma de decisiones relevantes de la patrulla»,
    y la guía dice dónde se anota: «Los acuerdos del Consejo pueden registrarse
    en el Libro de Oro o Libro de Patrulla». Esto es ese registro, con una
    diferencia: acá los acuerdos no se quedan escritos, van a buscar a quien se
    comprometió.
    """

    __tablename__ = "consejos_patrulla"

    id: Mapped[int] = mapped_column(primary_key=True)
    patrulla_id: Mapped[int] = mapped_column(ForeignKey("patrullas.id"), index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    temas: Mapped[str] = mapped_column(Text, default="")
    escribio_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    patrulla: Mapped[Patrulla] = relationship()
    escribio: Mapped[Usuario | None] = relationship()
    presentes: Mapped[list["PresenciaConsejo"]] = relationship(
        back_populates="consejo", cascade="all, delete-orphan"
    )
    acuerdos: Mapped[list["Acuerdo"]] = relationship(back_populates="consejo")


class PresenciaConsejo(Base):
    """Quiénes estuvieron en ese Consejo."""

    __tablename__ = "presencias_consejo"
    __table_args__ = (UniqueConstraint("consejo_id", "joven_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    consejo_id: Mapped[int] = mapped_column(ForeignKey("consejos_patrulla.id"))
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))

    consejo: Mapped[ConsejoPatrulla] = relationship(back_populates="presentes")
    joven: Mapped[Usuario] = relationship()


class Acuerdo(Base):
    """Algo que la patrulla decidió, con nombre y fecha.

    Un acuerdo sin responsable es un deseo. Por eso `responsable_id` y
    `para_cuando` existen, pero se pueden dejar vacíos: hay acuerdos que son de
    toda la patrulla («este ciclo acampamos dos veces») y obligar a poner un
    nombre los volvería mentira.
    """

    __tablename__ = "acuerdos"

    id: Mapped[int] = mapped_column(primary_key=True)
    consejo_id: Mapped[int | None] = mapped_column(
        ForeignKey("consejos_patrulla.id"), nullable=True
    )
    patrulla_id: Mapped[int] = mapped_column(ForeignKey("patrullas.id"), index=True)
    texto: Mapped[str] = mapped_column(Text)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    para_cuando: Mapped[date | None] = mapped_column(Date, nullable=True)
    cumplido: Mapped[bool] = mapped_column(Boolean, default=False)
    cumplido_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    consejo: Mapped[ConsejoPatrulla | None] = relationship(back_populates="acuerdos")
    patrulla: Mapped[Patrulla] = relationship()
    responsable: Mapped[Usuario | None] = relationship()


# --- Voz y voto: el Ciclo de Programa (cap. 8) -------------------------------


class Idea(Base):
    """Algo que alguien quiere hacer.

    El capítulo 8 es terminante: «las y los jóvenes tienen voz y voto respecto de
    las actividades que desean realizar». Sin esta tabla la aplicación solo sabe
    bajar tareas, que es exactamente lo que la guía describe como el modo de
    trabajar que hay que evitar.

    **La Asamblea no pasa por acá.** Se reúne en persona, y así tiene que
    seguir: es donde se aprende a discutir, a escuchar y a bancarse perder una
    votación mirando a la cara al que la ganó. Una pantalla no enseña eso. Lo
    que la aplicación hace es lo que un papelito en el bolsillo hace mal: juntar
    las propuestas para que lleguen enteras a esa reunión, y anotar después lo
    que la Unidad decidió.
    """

    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    # De qué patrulla salió. Sirve para el Consejo de Patrulla; proponer puede
    # cualquiera, venga de donde venga.
    patrulla_id: Mapped[int | None] = mapped_column(ForeignKey("patrullas.id"), nullable=True)
    autor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    titulo: Mapped[str] = mapped_column(String(200))
    texto: Mapped[str] = mapped_column(Text, default="")
    hace_falta: Mapped[str] = mapped_column(Text, default="")
    clase: Mapped[str] = mapped_column(String(20), default=CLASE_ACTIVIDAD)
    # unidad | patrulla: para quién sería.
    ambito: Mapped[str] = mapped_column(String(20), default=ALCANCE_UNIDAD)
    estado: Mapped[str] = mapped_column(String(20), default=IDEA_PROPUESTA)
    # Lo que el equipo anota al mirarla: por qué no se puede, qué haría falta.
    respuesta: Mapped[str] = mapped_column(Text, default="")
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    autor: Mapped[Usuario | None] = relationship()
    patrulla: Mapped[Patrulla | None] = relationship()
    apoyos: Mapped[list["ApoyoIdea"]] = relationship(
        back_populates="idea", cascade="all, delete-orphan"
    )

    @property
    def clase_nombre(self) -> str:
        return CLASES_ACTIVIDAD_NOMBRE.get(self.clase, self.clase)

    @property
    def clase_icono(self) -> str:
        return CLASES_ACTIVIDAD_ICONO.get(self.clase, "🎪")

    @property
    def estado_nombre(self) -> str:
        return IDEAS_ESTADO_NOMBRE.get(self.estado, self.estado)


class ApoyoIdea(Base):
    """«Yo me sumo».

    No es un voto y no decide nada: es saber cuántos la quieren antes de que la
    Unidad se junte a decidir. Un dato para llevar a la Asamblea, no un
    reemplazo de la Asamblea.
    """

    __tablename__ = "apoyos_idea"
    __table_args__ = (UniqueConstraint("idea_id", "joven_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"))
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    idea: Mapped[Idea] = relationship(back_populates="apoyos")
    joven: Mapped[Usuario] = relationship()


# --- El calendario del ciclo (cap. 8, fase 3) --------------------------------


class Actividad(Base):
    """Una fecha del calendario: qué se hace, cuándo y de quién es.

    El Consejo de Unidad arma el calendario y la Asamblea lo aprueba. Adentro van
    tanto las variables —lo que se eligió— como las fijas: campamentos,
    celebraciones, entregas de insignia.

    `idea_id` guarda de dónde salió, cuando salió de una idea de alguien. Que un
    chico vea su propuesta convertida en una fecha del calendario es la mitad del
    valor educativo de todo esto.
    """

    __tablename__ = "actividades"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    # Vacío = de toda la Unidad. Con patrulla = actividad de esa patrulla.
    patrulla_id: Mapped[int | None] = mapped_column(ForeignKey("patrullas.id"), nullable=True)
    titulo: Mapped[str] = mapped_column(String(200))
    detalle: Mapped[str] = mapped_column(Text, default="")
    lugar: Mapped[str] = mapped_column(String(160), default="")
    fecha: Mapped[date] = mapped_column(Date, index=True)
    # Para lo que dura más de un día: un campamento de viernes a domingo.
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    clase: Mapped[str] = mapped_column(String(20), default=CLASE_ACTIVIDAD)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("ideas.id"), nullable=True)
    creada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    patrulla: Mapped[Patrulla | None] = relationship()
    idea: Mapped[Idea | None] = relationship()
    participaciones: Mapped[list["ParticipacionActividad"]] = relationship(
        back_populates="actividad", cascade="all, delete-orphan"
    )

    @property
    def clase_nombre(self) -> str:
        return CLASES_ACTIVIDAD_NOMBRE.get(self.clase, self.clase)

    @property
    def clase_icono(self) -> str:
        return CLASES_ACTIVIDAD_ICONO.get(self.clase, "🎪")


class ParticipacionActividad(Base):
    """«Estuve». Lo marca el propio joven.

    No es una lista de asistencia que toma un adulto: es el joven diciendo dónde
    estuvo, y es lo que alimenta los requisitos de etapa que piden haber
    participado de una descubierta o de un proyecto (cap. 9). Coherente con que
    la evaluación de la progresión sea suya.
    """

    __tablename__ = "participaciones_actividad"
    __table_args__ = (UniqueConstraint("actividad_id", "joven_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"))
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    actividad: Mapped[Actividad] = relationship(back_populates="participaciones")
    joven: Mapped[Usuario] = relationship()


class EntradaLibroOro(Base):
    """Libro de Oro: la memoria colectiva de la Patrulla.

    Es la contraparte de la Bitácora de Aventura, que es personal e íntima. Acá
    escribe toda la patrulla y cada página queda firmada por quien la escribió.

    `fecha` es la del recuerdo —el campamento fue el sábado aunque las fotos se
    suban el miércoles—; `creada_en` es cuándo se cargó. El libro se ordena por
    la primera.
    """

    __tablename__ = "libro_oro"

    id: Mapped[int] = mapped_column(primary_key=True)
    patrulla_id: Mapped[int] = mapped_column(ForeignKey("patrullas.id"), index=True)
    # Si un día se da de baja a quien escribió, la página del libro se queda.
    autor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    titulo: Mapped[str] = mapped_column(String(200), default="")
    texto: Mapped[str] = mapped_column(Text, default="")
    archivo_foto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Del video se guarda el servicio y el identificador, nunca la URL cruda:
    # la de reproducción la arma servicios/medios.py.
    video_servicio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    video_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    # Bajada por el equipo. La página no se borra —borrarla es del autor, y es
    # otra cosa—: deja de verse y queda a la vista de quien la bajó, para poder
    # devolverla si fue un error.
    oculta_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    oculta_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    patrulla: Mapped[Patrulla] = relationship()
    autor: Mapped[Usuario | None] = relationship(foreign_keys=[autor_id])
    oculta_por: Mapped[Usuario | None] = relationship(foreign_keys=[oculta_por_id])
    # Igual que en Entrega: borrar la página se lleva los avisos que la señalaban.
    avisos: Mapped[list["Aviso"]] = relationship(
        back_populates="libro", cascade="all, delete-orphan"
    )

    @property
    def oculta(self) -> bool:
        return self.oculta_en is not None


# --- Avisar al equipo --------------------------------------------------------


class Aviso(Base):
    """«Esto que se publicó no está bien». Lo levanta cualquiera, lo mira el equipo.

    Acá se publica en el momento: una foto entra al muro o al Libro de Oro sin
    que un adulto la haya visto antes. La contraparte de esa inmediatez es que
    bajar algo tiene que ser rápido y que cualquiera pueda pedirlo — sobre todo
    quien aparece en la foto, que es el que primero se da cuenta y el que hoy no
    tenía ninguna forma de decirlo salvo esperar a la reunión del sábado.

    No decide nada por sí solo: no oculta la publicación ni la marca. Pone la
    foto arriba de todo en `/novedades` para que un educador la mire. Ocultar es
    siempre de una persona, igual que rechazar una entrega (ver
    `servicios/validacion.py`).

    Apunta a una entrega o a una página del libro, nunca a las dos. Son dos
    columnas y no una tabla polimórfica: son dos, se leen de un vistazo y el
    motor puede exigir la integridad de las dos.
    """

    __tablename__ = "avisos"
    # Uno por persona y por publicación: avisar dos veces no hace más ruido, y
    # sin esto un mismo aviso repetido tapa el resto de la lista.
    __table_args__ = (
        UniqueConstraint("entrega_id", "avisa_id"),
        UniqueConstraint("libro_id", "avisa_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    entrega_id: Mapped[int | None] = mapped_column(ForeignKey("entregas.id"), nullable=True)
    libro_id: Mapped[int | None] = mapped_column(ForeignKey("libro_oro.id"), nullable=True)
    avisa_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # Por qué. Puede venir vacío a propósito: exigir que un chico escriba un
    # párrafo para poder decir «esa foto es mía y no quiero que esté» sería
    # ponerle un peaje justo a quien más rápido tiene que poder avisar.
    motivo: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    atendido_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    atendido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    # Qué hizo el equipo. Se le muestra a quien avisó: alguien que avisa y no se
    # entera de nada no vuelve a avisar.
    resolucion: Mapped[str] = mapped_column(Text, default="")

    entrega: Mapped[Entrega | None] = relationship(back_populates="avisos")
    libro: Mapped[EntradaLibroOro | None] = relationship(back_populates="avisos")
    avisa: Mapped[Usuario] = relationship(foreign_keys=[avisa_id])
    atendido_por: Mapped[Usuario | None] = relationship(foreign_keys=[atendido_por_id])

    @property
    def atendido(self) -> bool:
        return self.atendido_en is not None


# --- De dónde salió cada cosa -------------------------------------------------
#
# Las dos tablas de acá abajo existen por un problema concreto: un Guía entrando
# con la cuenta de cada uno de sus patrulleros para completarles los retos, y
# relatos que llegan escritos por una IA. Las dos son de la misma familia —lo que
# se ve no lo hizo quien figura— y las dos son invisibles para todo lo que había
# hasta ahora, porque de una entrega solo quedaba el texto y la foto.
#
# La regla que las gobierna es la misma que ya rige `servicios/validacion.py` y no
# se mueve: **esto no acusa a nadie ni rechaza nada**. Guarda hechos verificables
# —de qué aparato salió, si el texto se tecleó o se pegó, si la foto trae datos de
# cámara— y se los pone adelante a un educador. Decidir qué significan es de una
# persona que conoce al chico, siempre. Un número no sabe que a Mateo se le rompió
# el teléfono y entrega desde el de la hermana.
#
# Y se dice de frente: la pantalla de entrega avisa que esto se registra, antes de
# que nadie escriba una palabra. Registrar en silencio para después sorprender a
# alguien con la prueba sería, además de feo, la peor manera de enseñar algo.

# Caracteres pegados de los que vale la pena hablar. Por debajo de esto es una
# palabra, un nombre propio o una dirección: cosas que se pegan todos los días.
PEGADO_MINIMO = 200


class Acceso(Base):
    """Un ingreso: quién entró, cuándo y desde qué aparato.

    Hasta acá una sesión no dejaba rastro de nada. Entrar con cinco cuentas
    seguidas desde el mismo teléfono y salir de cada una era, para la
    aplicación, exactamente igual que cinco chicos entrando desde su casa.

    No guarda qué hizo nadie adentro: eso ya está en lo que hizo. Guarda la
    puerta y nada más.
    """

    __tablename__ = "accesos"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    aparato: Mapped[str] = mapped_column(String(64), default="", index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    # Recortado y tal cual viene. Sirve para distinguir «el mismo aparato» de
    # «la misma casa»: dos hermanos con dos teléfonos comparten la dirección de
    # internet y no comparten el aparato, y esa diferencia es justo la que hay
    # que poder ver antes de decirle algo a alguien.
    navegador: Mapped[str] = mapped_column(String(200), default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, index=True)

    usuario: Mapped[Usuario] = relationship()


class Rastro(Base):
    """Cómo entró una entrega: de qué aparato, tecleada o pegada, con qué foto.

    **Lo que mide la escritura no es «esto lo escribió una IA».** Eso no se puede
    saber y quien diga que sí lo sabe está adivinando; los detectores de texto
    generado se equivocan seguido y equivocarse acá significa acusar en falso a un
    chico de doce por algo que efectivamente hizo. Lo que se guarda es un hecho y
    solo eso: cuántos caracteres entraron de un pegue y cuántos se teclearon uno
    por uno. «Pegaste 900 caracteres de una» no es una acusación, es algo que pasó,
    y a partir de ahí se conversa —capaz lo escribió en las notas del celular, que
    también pasa—.

    **Lo que mide la foto tampoco es una prueba.** Una foto sacada con la cámara
    trae adentro la marca y el modelo del teléfono; una generada por una IA no, y
    encima suele traer el sello C2PA que los generadores le ponen a propósito.
    Pero WhatsApp le borra los metadatos a todo lo que pasa por él, así que una
    foto reenviada por ahí llega igual de pelada que una inventada. Por eso es
    señal y nunca prueba.

    Del aparato no se deduce nada solo: que dos entregas salgan del mismo teléfono
    puede ser un Guía completándole los retos a su patrulla o dos hermanas que
    comparten el único celular de la casa. Son casos opuestos y desde el servidor
    se ven idénticos. Lo que la aplicación hace es mostrarlo; separarlos es de
    quien los conoce.
    """

    __tablename__ = "rastros_entrega"

    id: Mapped[int] = mapped_column(primary_key=True)
    entrega_id: Mapped[int] = mapped_column(ForeignKey("entregas.id"), unique=True)
    aparato: Mapped[str] = mapped_column(String(64), default="", index=True)

    # --- cómo entró el texto ---
    # Caracteres que llegaron de un pegue, y caracteres tecleados. Los cuenta el
    # navegador y los manda el formulario: se pueden falsear con la consola
    # abierta, y no importa. Esto no cierra ninguna puerta —no hay nada del otro
    # lado que proteger—, y quien sepa abrir las herramientas de desarrollo para
    # inflar un contador no era el problema que vinimos a resolver.
    pegado: Mapped[int] = mapped_column(Integer, default=0)
    tecleado: Mapped[int] = mapped_column(Integer, default=0)
    # Desde que tocó el cuadro de texto hasta que apretó enviar.
    segundos: Mapped[int] = mapped_column(Integer, default=0)

    # --- qué contaba la foto de sí misma ---
    # Se lee antes de guardarla y no queda ni un byte del EXIF en el disco: lo
    # que se conserva son estas tres cosas y el GPS sigue sin guardarse nunca
    # (ver `servicios/medios.py`).
    hubo_foto: Mapped[bool] = mapped_column(Boolean, default=False)
    # «Samsung SM-A515F». Vacío significa que no traía datos de cámara.
    foto_camara: Mapped[str] = mapped_column(String(120), default="")
    foto_tomada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    foto_software: Mapped[str] = mapped_column(String(120), default="")
    # El sello que los generadores de imágenes le ponen a lo que fabrican.
    foto_generada: Mapped[bool] = mapped_column(Boolean, default=False)

    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    entrega: Mapped[Entrega] = relationship(back_populates="rastro")

    @property
    def escrito(self) -> int:
        return self.pegado + self.tecleado

    @property
    def mayormente_pegado(self) -> bool:
        """Casi todo lo que hay en el cuadro llegó de un pegue.

        Con piso, porque pegar es normal y a veces es lo correcto: el nombre de
        un lugar, un link, una palabra que no sabía escribir. Lo que llama la
        atención es el relato entero de una sola vez.
        """
        return self.pegado >= PEGADO_MINIMO and self.pegado >= self.escrito * 0.8

    @property
    def foto_sin_camara(self) -> bool:
        return self.hubo_foto and not self.foto_camara
