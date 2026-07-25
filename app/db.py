"""Motor y sesión de SQLAlchemy sobre SQLite."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BASE_DATOS_URL

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
    cursor.execute("PRAGMA journal_mode=WAL")
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
