import logging
import unittest
from types import SimpleNamespace

logging.disable(logging.CRITICAL)


class _FakeQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *args, **kwargs):
        # We don't evaluate SQLAlchemy expressions in unit tests.
        return self

    def first(self):
        if not self._session._first_queue:
            return None
        return self._session._first_queue.pop(0)


class _FakeSession:
    def __init__(self, first_queue=None):
        self._first_queue = list(first_queue or [])

    def query(self, _model):
        return _FakeQuery(self)


class UserMappingLookupTests(unittest.TestCase):
    def test_get_user_mapping_direct(self):
        from app.services.sync_service import SyncService

        mapping = SimpleNamespace(target_username="bob")
        svc = SyncService(_FakeSession(first_queue=[mapping]))

        out = svc._get_user_mapping("alice", source_instance_id=1, target_instance_id=2)
        self.assertEqual(out, "bob")

    def test_get_user_mapping_reverse_fallback(self):
        from app.services.sync_service import SyncService

        # First query (direct) misses, second query (reverse) hits.
        reverse = SimpleNamespace(source_username="alice")
        svc = SyncService(_FakeSession(first_queue=[None, reverse]))

        out = svc._get_user_mapping("bob", source_instance_id=2, target_instance_id=1)
        self.assertEqual(out, "alice")

    def test_map_usernames_uses_catch_all_when_missing(self):
        from app.services.sync_service import SyncService

        svc = SyncService(_FakeSession(first_queue=[None, None]))
        out = svc._map_usernames(
            ["alice", "bob"],
            source_instance_id=1,
            target_instance_id=2,
            fallback_username="catchall",
        )
        self.assertEqual(out, ["catchall", "catchall"])

    def test_map_usernames_keeps_current_behavior_when_no_catch_all(self):
        from app.services.sync_service import SyncService

        svc = SyncService(_FakeSession(first_queue=[None, None]))
        out = svc._map_usernames(["alice", "bob"], source_instance_id=1, target_instance_id=2)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
