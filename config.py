"""Configuration de l'application.

Les paramètres sont chargés depuis les variables d'environnement (ou un fichier
``.env``). Les secrets ne sont jamais durcis dans le code source.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # python-dotenv optionnel : l'application fonctionne sans lui (environnements seulement).
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover - environnement sans python-dotenv
    def load_dotenv(override: bool = False) -> None:  # type: ignore[misc]
        """Repli : aucune action si python-dotenv est absent."""
        return None


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - défense en profondeur
        raise ValueError(f"La variable {name!r} doit être un entier (reçu: {raw!r})") from exc


def _get_str(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value


@dataclass(frozen=True)
class Settings:
    """Paramètres de connexion et de comportement de la collecte.

    ``frozen=True`` rend l'instance immuable une fois construite, ce qui évite les
    mutations accidentelles du côté des modules clients.
    """

    mongo_uri: str
    mongo_db_name: str
    mongo_collection_posts: str
    mongo_collection_comments: str
    meta_version: str
    meta_access_token: str
    meta_app_id: str
    instagram_business_account_id: str | None
    facebook_page_id: str | None
    search_limit: int
    posts_per_page: int
    retry_max_attempts: int
    rate_limit_retry_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Construit les paramètres depuis l'environnement.

        :raises ValueError: si une clé obligatoire est manquante ou invalide.
        """
        mongo_uri = _get_str("MONGO_URI", "mongodb://localhost:27017")
        db_name = _get_str("MONGO_DB_NAME", "social_media")
        posts_col = _get_str("MONGO_COLLECTION_POSTS", "posts")
        comments_col = _get_str("MONGO_COLLECTION_COMMENTS", "comments")
        version = _get_str("META_VERSION", "v21.0")
        access_token = _get_str("META_ACCESS_TOKEN")
        app_id = _get_str("META_APP_ID")
        ig_account = _get_str("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        fb_page = _get_str("FACEBOOK_PAGE_ID")

        if not access_token:
            raise ValueError(
                "META_ACCESS_TOKEN est obligatoire. Renseignez-le dans .env ou l'environnement."
            )
        if not app_id:
            raise ValueError(
                "META_APP_ID est obligatoire (App ID de l'application Meta for Developers)."
            )
            raise ValueError(
                "META_ACCESS_TOKEN est obligatoire. Renseignez-le dans .env ou l'environnement."
            )

        return cls(
            mongo_uri=mongo_uri,
            mongo_db_name=db_name,
            mongo_collection_posts=posts_col,
            mongo_collection_comments=comments_col,
            meta_version=version,
            meta_access_token=access_token,
            meta_app_id=app_id,
            instagram_business_account_id=ig_account,
            facebook_page_id=fb_page,
            search_limit=_get_int("SEARCH_LIMIT", 200),
            posts_per_page=_get_int("POSTS_PER_PAGE", 25),
            retry_max_attempts=_get_int("RETRY_MAX_ATTEMPTS", 5),
            rate_limit_retry_seconds=_get_int("RATE_LIMIT_RETRY_SECONDS", 60),
        )
