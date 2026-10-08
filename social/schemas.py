"""Modèles de données normalisés et sérialisables vers MongoDB.

L'API Meta expose des structures très différentes selon les plateformes
(Facebook vs Instagram). Ces modèles centralisent un format unique afin que le
stockage et l'orchestration soient indépendants de la source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Comment:
    """Commentaire lié à un post.

    ``post_id`` permet de retrouver rapidement tous les commentaires d'un post.
    ``author_id`` est laissé volontairement optionnel : certaines réponses d'API
    ne l'exposent pas sans scopes supplémentaires.
    """

    external_id: str
    post_id: str
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    permalink: Optional[str] = None

    def to_document(self) -> dict:
        return {
            "_id": self.external_id,
            "post_id": self.post_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "text": self.text,
            "created_at": self.created_at,
            "permalink": self.permalink,
        }


@dataclass
class Post:
    """Post (photo/image + texte) normalisé quelle que soit la plateforme."""

    external_id: str
    platform: str  # "facebook" | "instagram"
    caption: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)
    permalink: Optional[str] = None
    timestamp: Optional[datetime] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None

    def to_document(self) -> dict:
        return {
            "external_id": self.external_id,
            "platform": self.platform,
            "caption": self.caption,
            "image_urls": self.image_urls,
            "permalink": self.permalink,
            "timestamp": self.timestamp,
            "author_id": self.author_id,
            "author_name": self.author_name,
        }
