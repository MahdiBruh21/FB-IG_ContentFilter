"""DÉMO locale du pipeline de collecte (sans MongoDB).

MongoDB n'est pas joignable depuis ce sandbox (DNS bloquée), donc ce script
réutilise les chemins de production (MetaHttpClient + FacebookExtractor) pour
collecter les posts + commentaires de la page, puis les sauvegarde en JSON.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from logging_config import configure_logging

from config import Settings
from social.client import MetaHttpClient
from social.extractor import FacebookExtractor

configure_logging()


def main() -> None:
    settings = Settings.from_env()
    client = MetaHttpClient(
        access_token=settings.meta_access_token,
        version=settings.meta_version,
        max_attempts=settings.retry_max_attempts,
        app_id=settings.meta_app_id,
    )
    extractor = FacebookExtractor(client, settings)
    page_id = settings.facebook_page_id

    posts = []
    for raw in extractor._fetch_posts(page_id):
        post = extractor._normalize(raw, raw.get("from", {}).get("id"),
                                    raw.get("from", {}).get("name"))
        comments = extractor.get_comments(post)
        posts.append({
            "post": post.to_document(),
            "comment_count": len(comments),
            "comments": [c.to_document() for c in comments],
        })

    out = os.path.join(os.path.dirname(__file__), "demo_output.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(
            {"page_id": page_id, "posts": posts},
            fh,
            ensure_ascii=False,
            indent=2,
            default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o),
        )

    total_comments = sum(p["comment_count"] for p in posts)
    print(f"Collecte démo terminée : {len(posts)} post(s), {total_comments} commentaire(s).")
    print("Sauvegardé dans:", out)
    client.close()


if __name__ == "__main__":
    main()
