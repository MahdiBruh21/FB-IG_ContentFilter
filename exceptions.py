"""Hiérarchie d'exceptions de l'application.

Utiliser des exceptions dédiées permet à l'orchestrateur de réagir différemment
selon la nature de l'erreur (auth, limite de débit, réseau, stockage...).
"""
from __future__ import annotations


class SocialCollectorError(Exception):
    """Erreur générique de l'application."""


class ApiError(SocialCollectorError):
    """Échec retourné par l'API Graph de Meta."""


class AuthError(ApiError):
    """Jeton d'accès invalide, expiré ou dépourvu de scopes suffisants."""


class RateLimitError(ApiError):
    """Débit de l'API atteint (HTTP 429). Doit attendre et réessayer."""


class CollectionError(SocialCollectorError):
    """Échec lors de la collecte (réseau, pagination, format de réponse)."""


class StoreError(SocialCollectorError):
    """Échec lors de l'écriture ou la lecture de la base MongoDB."""
