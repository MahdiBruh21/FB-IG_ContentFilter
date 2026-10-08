"""Tests unitaires (dépendances standard uniquement).

Ils couvrent la normalisation des données, le parsing de la configuration et la
logique de déduplication du stockage, sans nécessiter MongoDB ni l'API.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from social.schemas import Comment, Post


class TestPostSchema(unittest.TestCase):
    def test_to_document_contains_required_fields(self):
        post = Post(
            external_id="123",
            platform="facebook",
            caption="salut",
            image_urls=["https://img/1.jpg"],
            timestamp=datetime(2022, 6, 26, tzinfo=timezone.utc),
        )
        doc = post.to_document()
        self.assertEqual(doc["external_id"], "123")
        self.assertEqual(doc["platform"], "facebook")
        self.assertEqual(doc["image_urls"], ["https://img/1.jpg"])
        self.assertIsInstance(doc["timestamp"], datetime)

    def test_empty_image_urls_defaults_to_list(self):
        post = Post(external_id="1", platform="instagram")
        self.assertEqual(post.image_urls, [])


class TestCommentSchema(unittest.TestCase):
    def test_to_document(self):
        comment = Comment(external_id="c1", post_id="p1", text="beau")
        doc = comment.to_document()
        self.assertEqual(doc["post_id"], "p1")
        self.assertEqual(doc["text"], "beau")


class TestSettingsFromEnv(unittest.TestCase):
    def _base_env(self) -> dict:
        return {
            "MONGO_URI": "mongodb://localhost:27017",
            "MONGO_DB_NAME": "testdb",
            "META_ACCESS_TOKEN": "TOKEN",
            "META_APP_ID": "123456",
        }

    def test_loads_defaults(self):
        # clear=True isole le test de tout .env réel présent dans le projet.
        env = self._base_env()
        with mock.patch.dict(os.environ, env, clear=True):
            settings = __import__("config", fromlist=["Settings"]).Settings.from_env()
        self.assertEqual(settings.mongo_db_name, "testdb")
        self.assertEqual(settings.meta_access_token, "TOKEN")
        self.assertEqual(settings.search_limit, 200)
        self.assertEqual(settings.posts_per_page, 25)

    def test_missing_token_raises(self):
        env = {"MONGO_URI": "mongodb://localhost:27017"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                __import__("config", fromlist=["Settings"]).Settings.from_env()


class FakeCollection:
    """Collection MongoDB factice pour tester la déduplication."""

    def __init__(self) -> None:
        self.docs: dict = {}

    def replace_one(self, filter_, document, upsert=False):
        key = (filter_.get("platform"), filter_.get("external_id"))
        if key in self.docs:
            class _R:
                upserted_id = None

            self.docs[key].update(document)
            return _R()
        if upsert:
            self.docs[key] = dict(document)
            class _R:
                def __init__(self):
                    self.upserted_id = "new"

            return _R()
        class _R:
            upserted_id = None

        return _R()

    def insert_many(self, documents, ordered=True):
        class _Result:
            def __init__(self, ids):
                self.inserted_ids = ids

        ids = [str(i) for i in range(len(documents))]
        for doc in documents:
            self.docs.setdefault(("_auto", doc.get("post_id", doc.get("external_id"))), doc)
        return _Result(ids)

    def count_documents(self, _filter=None):
        return len(self.docs)


def _make_settings():
    """Construit des paramètres valables sans passer par from_env (pas de jeton réel)."""
    from config import Settings

    return Settings(
        mongo_uri="mongodb://localhost:27017",
        mongo_db_name="testdb",
        mongo_collection_posts="posts",
        mongo_collection_comments="comments",
        meta_version="v21.0",
        meta_access_token="TOKEN",
        meta_app_id="123456",
        instagram_business_account_id=None,
        facebook_page_id=None,
        search_limit=200,
        posts_per_page=25,
        retry_max_attempts=5,
        rate_limit_retry_seconds=60,
    )


class TestMongoStoreDeduplication(unittest.TestCase):
    def setUp(self):
        import storage.mongo_store as store_module

        self.fake_posts = FakeCollection()
        self.fake_comments = FakeCollection()
        self.fake_db = type("Db", (), {"__getitem__": lambda self, name: self._make(name)})()
        self.fake_db._collections = {"posts": self.fake_posts, "comments": self.fake_comments}

        self.store_class = store_module.MongoStore

    def test_upsert_inserts_then_updates(self):
        store = self.store_class.__new__(self.store_class)  # contourne la connexion Mongo
        store.settings = _make_settings()
        store._posts = self.fake_posts
        store._comments = self.fake_comments

        post = Post(external_id="1", platform="facebook", caption="a")
        self.assertTrue(store.upsert_post(post))   # première insertion
        self.assertFalse(store.upsert_post(post))  # doublon -> pas de nouvelle insertion

    def test_add_comments_returns_count(self):
        store = self.store_class.__new__(self.store_class)
        store.settings = _make_settings()
        store._comments = self.fake_comments

        comments = [Comment(external_id=f"c{i}", post_id="p1") for i in range(3)]
        self.assertEqual(store.add_comments("p1", comments), 3)
        self.assertEqual(store.add_comments("p1", []), 0)


if __name__ == "__main__":
    unittest.main()
