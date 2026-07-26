"""Motor y sesión de SQLAlchemy sobre SQLite."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
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
