"""Client HTTP léger vers la Meta Graph API.

Il centralise :
  * l'authentification par jeton,
  * la gestion des erreurs (auth, limite de débit, réseau),
  * la pagination (suit l'URL ``paging.next``),
  * la réessaye exponentielle sur les limites de débit.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterator, Optional

import requests

from exceptions import ApiError, AuthError, CollectionError, RateLimitError

logger = logging.getLogger(__name__)


class MetaHttpClient:
    """Client HTTP pour ``https://graph.facebook.com/<version>/...``."""

    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        access_token: str,
        version: str = "v21.0",
        max_attempts: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
        app_id: str | None = None,
    ) -> None:
        self.access_token = access_token
        # Jeton "base" (user token) : jamais modifié. Le jeton page (posible) est
        # appliqué via page_token et utilisé uniquement pour les ops liées à une
        # page (posts/commentaires). search/mint utilisent toujours l'user token.
        self.page_token: str | None = None
        self.version = version
        self.app_id = app_id
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._session = requests.Session()

    def _current_token(self) -> str:
        """Jeton effectif : page token si défini, sinon user token."""
        return self.page_token or self.access_token

    def use_page_token(self, token: str) -> None:
        """Active le jeton page pour les requêtes suivantes (posts/commentaires)."""
        self.page_token = token

    def use_user_token(self) -> None:
        """Réinitialise au user token (search, mint)."""
        self.page_token = None

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _url(endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return f"{MetaHttpClient.BASE_URL}/{endpoint.lstrip('/')}"

    def _backoff(self, attempt: int) -> float:
        """Déai exponentiel borné : base * 2**(n-1), plafonné."""
        return min(self.base_backoff * (2 ** (attempt - 1)), self.max_backoff)

    # -- requêtes --------------------------------------------------------
    def request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
    ) -> Dict[str, Any]:
        """Exécute une requête avec retry et renvoie le JSON reçu.

        :raises AuthError: si le jeton est rejeté (400/401/403).
        :raises RateLimitError: si le débit est limité (429).
        :raises ApiError: pour toute autre erreur HTTP ou payload d'erreur.
        :raises CollectionError: en cas d'erreur réseau réitérée.
        """
        params = dict(params or {})
        params["access_token"] = self._current_token()
        if self.app_id:
            params["app_id"] = self.app_id

        last_network_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._session.request(
                    method,
                    self._url(endpoint),
                    params=params,
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_network_error = exc
                logger.warning("Erreur réseau (%s), essai %s/%s", exc, attempt, self.max_attempts)
                if attempt < self.max_attempts:
                    time.sleep(self._backoff(attempt))
                continue

            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", self._backoff(attempt)))
                logger.warning("Débit limité (429), en attente de %ss (%s/%s)", wait, attempt, self.max_attempts)
                time.sleep(wait)
                continue

            if response.status_code in (400, 401, 403):
                raise AuthError(f"Authification échouée ({response.status_code}): {response.text[:200]}")

            if response.status_code >= 400:
                raise ApiError(f"Erreur HTTP {response.status_code}: {response.text[:200]}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise CollectionError("Réponse JSON invalide de l'API.") from exc

            if isinstance(payload, dict) and payload.get("error"):
                error = payload["error"]
                code = error.get("code")
                message = error.get("message", "erreur inconnue")
                # Code 190 = jeton expiré, 4/100 = scope manquant
                if code in (190, 104) or response.status_code in (401, 403):
                    raise AuthError(f"Jeton invalide/expiré ou scope manquant: {message}")
                raise ApiError(f"[{code}] {message}")

            return payload

        raise CollectionError(f"Échec après {self.max_attempts} essais: {last_network_error}")

    def get_paginated(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """Itère sur toutes les pages d'une collection, en suivant ``paging.next``.

        La première requête doit transporter ``access_token``/``app_id`` ; les pages
        suivantes réutilisent l'URL ``paging.next`` qui les contient déjà (on ne les
        remet donc pas pour éviter les doublons de query-string).
        """
        params = dict(params or {})
        params["limit"] = 25
        if self.app_id:
            params["app_id"] = self.app_id
        url = self._url(endpoint)
        first = True

        while url:
            if first:
                params["access_token"] = self._current_token()
                response = self._session.get(url, params=params, timeout=30)
                first = False
            else:
                # ``paging.next`` contient déjà jeton, app_id, fields, limit.
                response = self._session.get(url, timeout=30)
            if response.status_code >= 400:
                raise ApiError(f"Erreur HTTP {response.status_code} (pagination): {response.text[:200]}")
            payload = response.json()

            for item in payload.get("data", []):
                yield item

            paging = payload.get("paging", {})
            url = paging.get("next")

    def search(self, query: str, search_type: str, limit: int) -> list[dict]:
        """Recherche (pages, hashtags, utilisateurs...) liée au sujet."""
        params: Dict[str, Any] = {"q": query, "type": search_type, "limit": min(limit, 50)}
        return self.request("search", params).get("data", [])

    def account_accessible(self, account_id: str) -> bool:
        """Renvoit True si ``account_id`` (FB Page ou IG Business Account) est lisible."""
        try:
            payload = self.request(account_id, {"fields": "id"})
            return bool(payload.get("id"))
        except ApiError:
            return False

    def get_linked_instagram(self, page_id: str) -> str | None:
        """Renvoit l'Instagram Business Account relié à la Page ``page_id``, sinon None."""
        try:
            payload = self.request(page_id, {"fields": "instagram_business_account"})
        except ApiError:
            return None
        return (payload.get("instagram_business_account") or {}).get("id")

    def close(self) -> None:
        self._session.close()
