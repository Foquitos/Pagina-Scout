"""Motor y sesión de SQLAlchemy sobre SQLite."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, exists, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BASE_DATOS_URL, SQLITE_ESPERA_MS, SQLITE_JOURNAL

motor = create_engine(
    BASE_DATOS_URL,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(motor, "connect")
def _configurar_sqlite(conexion, _registro):
    """SQLite no aplica claves foráneas salvo que se pidan explícitamente."""
    cursor = conexion.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # Los dos salen de config.py porque cambian según dónde viva el archivo:
    # un disco local y un recurso de red no aguantan lo mismo.
    cursor.execute(f"PRAGMA journal_mode={SQLITE_JOURNAL}")
    cursor.execute(f"PRAGMA busy_timeout={SQLITE_ESPERA_MS}")
    cursor.close()


SesionLocal = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por request."""
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


def hay_referencias_a(sesion: Session, tabla: str, id_: int) -> bool:
    """¿Queda alguna fila en toda la base apuntando a `tabla.id == id_`?

    Es lo que separa «esto se puede borrar de verdad» de «esto hay que
    desactivar». Una patrulla que llenó su Libro de Oro o un educador que firmó
    cambios de etapa no se borran: hacerlo dejaría huecos donde hoy hay un
    nombre. Una fila que no dejó rastro —la patrulla creada por error, el usuario
    que se escribió mal— sí, y guardarla como «inactiva» sería juntar basura.

    Se recorre el esquema en vez de escribir a mano la lista de tablas. Son
    veinticinco tablas y casi cuarenta columnas con clave foránea; esa lista a
    mano se desactualiza en cuanto alguien suma un modelo, y el modo de fallar
    sería borrar algo que sí tenía referencias, que es el error que no se puede
    cometer acá. Preguntándole al esquema, una tabla nueva queda cubierta el día
    que se crea.

    Corta en el primer hallazgo. En el peor caso son unas decenas de consultas
    de existencia sobre tablas chicas, en pantallas que se abren muy de vez en
    cuando.
    """
    for otra in Base.metadata.sorted_tables:
        for columna in otra.columns:
            if not any(fk.column.table.name == tabla for fk in columna.foreign_keys):
                continue
            if sesion.scalar(select(exists().where(columna == id_))):
                return True
    return False
