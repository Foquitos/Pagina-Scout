"""Modelo de datos.

El vocabulario sigue el del Método Scout (Rama Scouts / Unidad) para que el
código se lea igual que la guía: Unidad, Patrulla, competencia, desafío, etapa.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

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


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# --- Organización ------------------------------------------------------------


class Unidad(Base):
    __tablename__ = "unidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    grupo: Mapped[str] = mapped_column(String(120), default="")

    patrullas: Mapped[list["Patrulla"]] = relationship(back_populates="unidad")
    miembros: Mapped[list["Usuario"]] = relationship(back_populates="unidad")


class Patrulla(Base):
    __tablename__ = "patrullas"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"))
    nombre: Mapped[str] = mapped_column(String(80))
    lema: Mapped[str] = mapped_column(String(200), default="")
    color: Mapped[str] = mapped_column(String(20), default="#3E8E5A")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)

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
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    unidad: Mapped[Unidad | None] = relationship(back_populates="miembros")
    patrulla: Mapped[Patrulla | None] = relationship(back_populates="integrantes")

    @property
    def es_educador(self) -> bool:
        return self.rol == ROL_EDUCADOR

    @property
    def etapa_nombre(self) -> str:
        return ETAPAS_NOMBRE.get(self.etapa, self.etapa)


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
    """Las 12 a 14 cartas que cada joven elige para su etapa actual."""

    __tablename__ = "competencias_elegidas"
    __table_args__ = (UniqueConstraint("joven_id", "competencia_id", "etapa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    joven_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    competencia_id: Mapped[int] = mapped_column(ForeignKey("competencias.id"))
    etapa: Mapped[str] = mapped_column(String(20))
    lograda: Mapped[bool] = mapped_column(Boolean, default=False)
    elegida_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    lograda_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    competencia: Mapped[Competencia] = relationship()
    joven: Mapped[Usuario] = relationship()


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

    estado: Mapped[str] = mapped_column(String(20), default=ESTADO_PENDIENTE)
    devolucion: Mapped[str] = mapped_column(Text, default="")
    validada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    validador: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    puntaje_otorgado: Mapped[int] = mapped_column(Integer, default=0)

    asignacion: Mapped[Asignacion] = relationship(back_populates="entregas")
    joven: Mapped[Usuario] = relationship(foreign_keys=[joven_id])
    patrulla: Mapped[Patrulla | None] = relationship(foreign_keys=[patrulla_id])
    validada_por: Mapped[Usuario | None] = relationship(foreign_keys=[validada_por_id])


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

    patrulla: Mapped[Patrulla] = relationship()
    autor: Mapped[Usuario | None] = relationship()
