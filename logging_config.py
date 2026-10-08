"""Configuration centralisée du logging.

Le niveau est contrôlé par la variable d'environnement ``LOG_LEVEL``.
Tous les modules récupèrent un journal via ``logging.getLogger(__name__)``.
"""
from __future__ import annotations

import logging
import os

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Configure le logger racine une seule fois (idempotent)."""
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    logger = logging.getLogger()
    if logger.handlers:  # déjà configuré
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level, logging.INFO))
