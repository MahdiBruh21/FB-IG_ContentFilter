"""Extracteurs par plateforme.

Chaque extraitur convertit les réponses brutes de la Graph API vers les modèles
normalisés :class:`Post` / :class:`Comment`. Le strategy de recherche dépend de la
plateforme :

  * **Facebook** : on recherche des *pages* liées au sujet puis leurs posts.
  * **Instagram** : on recherche des *hashtags* puis les média associés.

Cette distinction reflète la réalité de l'API : Meta n'explose pas de recherche
globale de posts publics par mot-clé.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator, List, Optional

from config import Settings
from exceptions import CollectionError
from social.client import MetaHttpClient
from social.schemas import Comment, Post

logger = logging.getLogger(__name__)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse une ISO-8601 (avec décalage ``+0000``) en datetime aware, sinon None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Format de date non reconnu: %r", value)
        return None


class BaseExtractor(ABC):
    """Interface commune à tous les extracteurs."""

    PLATFORM: str = ""

    def __init__(self, client: MetaHttpClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    @abstractmethod
    def collect(self, query: str) -> Iterator[Post]:
        """Renvoit les posts correspondant au sujet."""

    @abstractmethod
    def get_comments(self, post: Post) -> List[Comment]:
        """Renvoit les commentaires d'un post (peut retourner une liste vide)."""


class FacebookExtractor(BaseExtractor):
    """Collecte les posts des pages Facebook liées au sujet."""

    PLATFORM = "facebook"

    def __init__(self, client: MetaHttpClient, settings: Settings) -> None:
        super().__init__(client, settings)
        # Un User Access Token ne peut pas lire les posts d'une page : on échange
        # l'utilisateur contre un Page Access Token (nécessite pages_read_engagement).
        if not settings.facebook_page_id:
            raise CollectionError("FACEBOOK_PAGE_ID est requis pour la plateforme Facebook.")
        # Cache de jetons page par page_id (un jeton est lié à une seule page).
        self._page_tokens: dict[str, str] = {}
        self._ensure_page_token(settings.facebook_page_id)

    def _ensure_page_token(self, page_id: str) -> str:
        """Retrouve (ou obtient et met en cache) le Page Access Token d'une page."""
        if page_id not in self._page_tokens:
            self._page_tokens[page_id] = self._mint_page_token(page_id)
        return self._page_tokens[page_id]

    def _mint_page_token(self, page_id: str) -> str:
        """Échange l'user token (base) contre un page token pour la page donnée."""
        # use_user_token garantit que l'échange se fait avec l'user token, jamais
        # avec un jeton page déjà acquis.
        self.client.use_user_token()
        raw = self.client.request(page_id, {"fields": "access_token"})
        token = raw.get("access_token")
        if not token:
            raise CollectionError("Impossible d'obtenir un Page Access Token pour cette page.")
        logger.info("Page Access Token obtenu pour la page %s.", page_id)
        return token

    def _search_pages(self, query: str) -> list[dict]:
        # La recherche exige l'user token (pages_show_list), pas un jeton page.
        self.client.use_user_token()
        return self.client.search(query, search_type="page", limit=self.settings.search_limit)

    def _fetch_posts(self, page_id: str) -> Iterator[dict]:
        # NB : le champ "caption" renvoie une erreur #12 côté API (field déprécié),
        token = self._ensure_page_token(page_id)
        self.client.use_page_token(token)
        fields = (
            "id,story,message,created_time,permalink,from,full_picture,images"
        )
        yield from self.client.get_paginated(
            f"{page_id}/posts",
            {"fields": fields},
        )

    def _pages_to_collect(self, query: str) -> list[tuple[str, str | None, str | None]]:
        """Renvoit la liste des (page_id, author_id, author_name) à collecter.

        Priorite la page configurée (accessibles et sûres), puis ajoute
        best-effort les pages issues de la recherche (gracieusement ignorées si
        le jeton n'y a pas accès).
        """
        result: list[tuple[str, str | None, str | None]] = []
        # Page configurée en premier (source fiable et accessible).
        result.append((self.settings.facebook_page_id, None, None))
        # Recherche de pages liées au sujet (meilleure intention, résultat variable).
        for page in self._search_pages(query):
            page_id = page.get("id")
            author = page.get("from") or page
            result.append((page_id, author.get("id"), author.get("name")))
        return result

    def collect(self, query: str) -> Iterator[Post]:
        pages = self._pages_to_collect(query)
        logger.info("Facebook : %s source(s) de pages identifiée(s) pour %r", len(pages), query)
        for page_id, author_id, author_name in pages:
            try:
                self._ensure_page_token(page_id)
            except CollectionError as exc:
                # Page non accessible pour ce jeton : on l'ignore et on continue.
                logger.warning("Page %s ignorée (%s).", page_id, exc)
                continue
            for raw in self._fetch_posts(page_id):
                yield self._normalize(raw, author_id, author_name)

    def _normalize(self, raw: dict, author_id, author_name) -> Post:
        # author_name fourni par la recherche (page trouvée) prime sur le champ 'from'.
        author_name = author_name or (raw.get("from") or {}).get("name")
        author_id = author_id or (raw.get("from") or {}).get("id")
        images: List[str] = []
        for img in raw.get("images", []) or []:
            url = img.get("url")
            if url:
                images.append(url)
        if not images:
            full_picture = raw.get("full_picture") or raw.get("backdated_picture")
            if full_picture:
                images.append(full_picture)
        return Post(
            external_id=str(raw["id"]),
            platform=self.PLATFORM,
            caption=raw.get("story") or raw.get("message"),
            image_urls=images,
            permalink=raw.get("permalink"),
            timestamp=_parse_timestamp(raw.get("created_time")),
            author_id=author_id,
            author_name=author_name,
        )

    def get_comments(self, post: Post) -> List[Comment]:
        fields = "id,from,message,created_time,permalink"
        payload = self.client.request(f"{post.external_id}/comments", {"fields": fields})
        comments: List[Comment] = []
        for raw in payload.get("data", []):
            frm = raw.get("from") or {}
            comments.append(
                Comment(
                    external_id=str(raw["id"]),
                    post_id=post.external_id,
                    author_id=frm.get("id"),
                    author_name=frm.get("name"),
                    text=raw.get("message"),
                    created_at=_parse_timestamp(raw.get("created_time")),
                    permalink=raw.get("permalink"),
                )
            )
        return comments


class InstagramExtractor(BaseExtractor):
    """Collecte les média (images) des hashtags liés au sujet."""

    PLATFORM = "instagram"

    def __init__(self, client: MetaHttpClient, settings: Settings) -> None:
        super().__init__(client, settings)
        if not settings.instagram_business_account_id:
            raise CollectionError("INSTAGRAM_BUSINESS_ACCOUNT_ID est requis pour Instagram.")
        # Meilleure intention : si le ID configuré n'est pas accessible, tenter de
        # résoudre le vrai Business Account depuis la Page Facebook reliée.
        self._account_id = self._resolve_account_id(settings.instagram_business_account_id)
        logger.info("Instagram : Business Account %s utilisé.", self._account_id)

    def _resolve_account_id(self, configured: str) -> str:
        if self.client.account_accessible(configured):
            return configured
        if self.settings.facebook_page_id and self.client.account_accessible(self.settings.facebook_page_id):
            linked = self.client.get_linked_instagram(self.settings.facebook_page_id)
            if linked:
                logger.info("Business Account Instagram résolu depuis la Page FB : %s", linked)
                return linked
        logger.warning(
            "Instagram %s introuvable : vérifier scope 'instagram_basic' et compte relié."
            " (le ID configuré sera conservé).",
            configured,
        )
        return configured

    def _fetch_account_media(self) -> Iterator[dict]:
        # `instagram_basic` n'autorise PAS la recherche de hashtags publics
        # (400 / subcode 33). On récupère donc les médias DU COMPTE relié.
        fields = (
            "id,caption,media_type,media_url,thumbnail_url,timestamp,permalink,username,from"
        )
        yield from self.client.get_paginated(
            f"{self._account_id}/media",
            {"fields": fields},
        )

    def collect(self, query: str) -> Iterator[Post]:
        # Collecte les médias du comptre Instagram relié ; le sujet filtre best-effort
        # sur la légende (instagram_basic ne permet pas de recherche publique).
        needle = (query or "").strip().lower()
        logger.info("Instagram : collecte du comptre relié %s (query=%r)", self._account_id, query)
        count = 0
        for raw in self._fetch_account_media():
            caption = (raw.get("caption") or "").lower()
            if needle and needle not in caption:
                continue
            count += 1
            yield self._normalize(raw, None)
        logger.info("Instagram : %s média(s) correspondant(s) pour %r", count, query)

    def _normalize(self, raw: dict, tag_name: Optional[str]) -> Post:
        # Seuls les media de type IMAGE contiennent une vraie photo.
        if raw.get("media_type") != "IMAGE":
            url = raw.get("media_url")
        else:
            url = raw.get("media_url") or raw.get("thumbnail_url")
        return Post(
            external_id=str(raw["id"]),
            platform=self.PLATFORM,
            caption=raw.get("caption"),
            image_urls=[url] if url else [],
            permalink=raw.get("permalink"),
            timestamp=_parse_timestamp(raw.get("timestamp")),
            author_id=raw.get("from", {}).get("id") if raw.get("from") else None,
            author_name=raw.get("username") or tag_name,
        )

    def get_comments(self, post: Post) -> List[Comment]:
        fields = "id,username,message,timestamp,permalink"
        payload = self.client.request(f"{post.external_id}/comments", {"fields": fields})
        comments: List[Comment] = []
        for raw in payload.get("data", []):
            comments.append(
                Comment(
                    external_id=str(raw["id"]),
                    post_id=post.external_id,
                    author_id=raw.get("username"),
                    author_name=raw.get("username"),
                    text=raw.get("message"),
                    created_at=_parse_timestamp(raw.get("timestamp")),
                    permalink=raw.get("permalink"),
                )
            )
        return comments
