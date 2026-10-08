"""Collecteur : orchestre la recherche, la collecte des posts/commentaires et le stockage."""
from __future__ import annotations

import logging
from typing import List

from config import Settings
from exceptions import CollectionError
from social.client import MetaHttpClient
from social.extractor import BaseExtractor
from social.schemas import Comment, Post
from storage.mongo_store import MongoStore

logger = logging.getLogger(__name__)


class Collector:
    """Pilote une collecte complète pour un sujet donné.

    Flux : recherche -> posts -> commentaires -> stockage (MongoDB).
    La déduplication repose sur l'index unique (platform, external_id) de Mongo,
    ce qui rend une relance idempotente.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = MetaHttpClient(
            access_token=settings.meta_access_token,
            version=settings.meta_version,
            max_attempts=settings.retry_max_attempts,
            app_id=settings.meta_app_id,
        )
        self.store = MongoStore(settings)
        self.extractor: BaseExtractor | None = None

    def _build_extractor(self, platform: str) -> BaseExtractor:
        from social.extractor import FacebookExtractor, InstagramExtractor

        if platform == "facebook":
            if not self.settings.facebook_page_id:
                raise CollectionError("FACEBOOK_PAGE_ID est requis pour la plateforme Facebook.")
            return FacebookExtractor(self.client, self.settings)
        if platform == "instagram":
            if not self.settings.instagram_business_account_id:
                raise CollectionError(
                    "INSTAGRAM_BUSINESS_ACCOUNT_ID est requis pour Instagram (recherche par hashtag)."
                )
            return InstagramExtractor(self.client, self.settings)
        raise CollectionError(f"Plateforme inconnue : {platform!r} (attendu facebook ou instagram)")

    def run(self, query: str, platform: str) -> dict:
        """Lance la collecte pour ``query`` et renvoie un résumé statistique."""
        self.extractor = self._build_extractor(platform)
        self.store.ensure_indexes()

        new_posts, total_comments = 0, 0
        try:
            for post in self.extractor.collect(query):
                if new_posts >= self.settings.search_limit:
                    logger.info("Limite de collecte atteinte (%s posts). Arrêt.", self.settings.search_limit)
                    break

                inserted = self.store.upsert_post(post)
                if inserted:
                    new_posts += 1
                    logger.info(
                        "[%s] post %s collecté (%s image(s))",
                        platform,
                        post.external_id,
                        len(post.image_urls),
                    )

                comments = self.extractor.get_comments(post)
                self.store.add_comments(post.external_id, comments)
                total_comments += len(comments)
        finally:
            self.store.close()
            self.client.close()

        summary = {
            "query": query,
            "platform": platform,
            "new_posts": new_posts,
            "total_comments": total_comments,
        }
        logger.info("Collecte terminée : %s", summary)
        return summary
