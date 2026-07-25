"""Arranque de la aplicación en desarrollo:  python main.py"""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PUERTO", 8000)),
        reload=True,
    )
