"""Stockage MongoDB des posts et commentaires.

Utilise pymongo avec :
  * upsert par clé unique (platform, external_id) pour éviter les doublons,
  * index pour des recherches rapides,
  * gestion des erreurs de connexion transformées en :class:`StoreError`.
"""
from __future__ import annotations

import logging
from typing import List

from config import Settings
from exceptions import StoreError
from social.schemas import Comment, Post

logger = logging.getLogger(__name__)


class MongoStore:
    """Facade simple autour de pymongo."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            from pymongo import MongoClient

            self._client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
            # Vérifie immédiatement la connexion (échôt tôt, pas à la première écriture).
            self._client.admin.command("ping")
        except Exception as exc:  # pymongo.errors.PyMongoError ou TimeoutError
            raise StoreError(f"Impossible de se connecter à MongoDB: {exc}") from exc

        self._db = self._client[settings.mongo_db_name]
        self._posts = self._db[settings.mongo_collection_posts]
        self._comments = self._db[settings.mongo_collection_comments]

    def ensure_indexes(self) -> None:
        """Crée les index utiles (unicité des posts, requêtes par post)."""
        self._posts.create_index(
            [("platform", 1), ("external_id", 1)], unique=True, name="unique_post"
        )
        self._posts.create_index("caption", name="caption_text", default_language="french")
        self._comments.create_index("post_id", name="comment_post_id")

    def upsert_post(self, post: Post) -> bool:
        """Insère ou met à jour un post. Renvoit ``True`` s'il a été créé."""
        try:
            result = self._posts.replace_one(
                {"platform": post.platform, "external_id": post.external_id},
                post.to_document(),
                upsert=True,
            )
            return result.upserted_id is not None
        except Exception as exc:
            raise StoreError(f"Échec d'écriture du post {post.external_id}: {exc}") from exc

    def add_comments(self, post_id: str, comments: List[Comment]) -> int:
        """Insère par lot les commentaires d'un post. Renvoit le nombre inséré."""
        if not comments:
            return 0
        documents = [comment.to_document() for comment in comments]
        try:
            result = self._comments.insert_many(documents, ordered=False)
            return len(result.inserted_ids)
        except Exception as exc:
            raise StoreError(f"Échec d'écriture des commentaires de {post_id}: {exc}") from exc

    def stats(self) -> dict:
        """Renvoit le nombre de documents par collection (utile pour les tests/debug)."""
        return {
            "posts": self._posts.count_documents({}),
            "comments": self._comments.count_documents({}),
        }

    def close(self) -> None:
        self._client.close()
