"""ASGI entrypoint.

Chạy:  uvicorn app:app --reload
Docs:  http://localhost:8000/docs

Toàn bộ wiring nằm ở composition root (legalguard/config/container.py).
"""
from legalguard.config.container import build_app

app = build_app()
