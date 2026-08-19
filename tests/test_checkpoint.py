import tempfile
import unittest
from pathlib import Path

from akita_supermodem.checkpoint import SessionCheckpointStore


class TestSessionCheckpointStore(unittest.TestCase):
    def test_round_trip_and_wrong_psk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionCheckpointStore(temp_dir, b"test-shared-secret")
            payload = {"session_id": "abc123", "shared_key": "aa" * 32, "receive": {"filename": "a.bin"}}
            store.save("abc123", payload)
            self.assertEqual(store.load("abc123")["receive"]["filename"], "a.bin")
            self.assertTrue((Path(temp_dir) / "abc123" / "session.chk").exists())

            other = SessionCheckpointStore(temp_dir, b"other-shared-secret")
            self.assertIsNone(other.load("abc123"))

            store.delete("abc123")
            self.assertIsNone(store.load("abc123"))
