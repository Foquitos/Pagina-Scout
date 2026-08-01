"""Arranque de la aplicación en desarrollo:  python main.py

Antes de levantar el servidor pone la base al día, que es exactamente lo que
hace `docker/entrypoint.sh` en el servidor. Sin esto, el día que alguien suma
una tabla o una columna, `git pull` y `python main.py` arrancan una aplicación
que revienta con «no such table» en la primera pantalla que la use —y el
traceback no dice en ningún lado que lo que falta es correr un script—.

Es idempotente: sobre una base al día no cambia nada, solo imprime el resumen de
las cartas. Corre una sola vez por `python main.py` —en el proceso padre—, no en
cada recarga por cambio de archivo.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import uvicorn

RAIZ = Path(__file__).resolve().parent


def poner_la_base_al_dia() -> None:
    """Corre `scripts/inicializar_db.py` en un proceso aparte.

    En un proceso aparte y no importándolo: el script abre el motor y carga las
    cartas, y hacerlo dentro de este intérprete dejaría esa conexión colgada en
    el proceso padre de `--reload`, que no es quien después sirve los pedidos.
    """
    resultado = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "inicializar_db.py")],
        cwd=RAIZ,
    )
    if resultado.returncode != 0:
        # Sin base al día no tiene sentido levantar: la aplicación andaría hasta
        # la primera pantalla que toque lo que falta.
        sys.exit(
            "\nNo se pudo poner la base al día, así que no se levanta el servidor.\n"
            "Si la base está abierta por otro proceso, cerralo y probá de nuevo."
        )


if __name__ == "__main__":
    # Con reload=True uvicorn se relanza a sí mismo en cada cambio de archivo.
    # Esto corre en el proceso padre, una sola vez, y no en cada recarga.
    poner_la_base_al_dia()
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PUERTO", 8000)),
        reload=True,
    )
