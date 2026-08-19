"""
Unit tests for AkitaReceiver.
"""

import unittest
from unittest.mock import Mock
from akita_supermodem.receiver import AkitaReceiver


class TestAkitaReceiver(unittest.TestCase):
    """Test AkitaReceiver functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_save = Mock()
        self.mock_send = Mock()
        self.receiver = AkitaReceiver(save_function=self.mock_save, send_function=self.mock_send)

    def test_init(self):
        """Test receiver initialization."""
        self.assertIsNotNone(self.receiver.save)
        self.assertIsNotNone(self.receiver.send)
        self.assertIsNotNone(self.receiver._lock)  # Thread lock should exist

    def test_get_transfer_id(self):
        """Test transfer ID generation."""
        # Direct message
        transfer_id = self.receiver._get_transfer_id("sender123", False)
        self.assertEqual(transfer_id, "sender123")

        # Broadcast
        transfer_id = self.receiver._get_transfer_id("sender123", True)
        self.assertEqual(transfer_id, "broadcast_sender123")

    def test_calculate_merkle_root(self):
        """Test Merkle root calculation."""
        num_pieces = 3
        received_hashes = {0: "a" * 64, 1: "b" * 64, 2: "c" * 64}
        root = self.receiver._calculate_merkle_root(num_pieces, received_hashes)
        self.assertIsNotNone(root)
        self.assertIsInstance(root, str)

    def test_calculate_merkle_root_missing(self):
        """Test Merkle root with missing hashes."""
        num_pieces = 3
        received_hashes = {
            0: "a" * 64,
            # Missing 1 and 2
        }
        root = self.receiver._calculate_merkle_root(num_pieces, received_hashes)
        self.assertIsNone(root)  # Should return None if hashes missing

    def test_check_for_missing_or_corrupt(self):
        """Test missing piece detection."""
        transfer_id = "test_transfer"
        self.receiver.active_transfers[transfer_id] = {
            "num_pieces": 5,
            "received_pieces": {0: b"data", 2: b"data"},  # Missing 1, 3, 4
            "retry_count": {},
            "failed": False,
            "transfer_complete": False,
        }

        missing = self.receiver._check_for_missing_or_corrupt(transfer_id)
        self.assertEqual(len(missing), 3)  # Should find 3 missing pieces
        self.assertIn(1, missing)
        self.assertIn(3, missing)
        self.assertIn(4, missing)

    def test_empty_file_start_does_not_deadlock(self):
        from akita_supermodem.generated import akita_pb2

        file_start = akita_pb2.FileStart(filename="empty.bin", total_size=0, piece_size=0)
        self.receiver.handle_file_start("!sender", file_start)
        self.assertEqual(self.receiver.active_transfers, {})
        self.mock_save.assert_called_once_with("empty.bin", b"")

    def test_duplicate_file_start_does_not_deadlock(self):
        from akita_supermodem.generated import akita_pb2

        file_start = akita_pb2.FileStart(filename="x.bin", total_size=1024, piece_size=128)
        self.receiver.handle_file_start("!sender", file_start)
        self.receiver.handle_file_start("!sender", file_start)
        self.assertIn("!sender", self.receiver.active_transfers)

    def test_max_retries_cleanup_does_not_deadlock(self):
        transfer_id = "!sender"
        self.receiver.max_retries = 1
        self.receiver.active_transfers[transfer_id] = {
            "num_pieces": 2,
            "received_pieces": {},
            "retry_count": {0: 1, 1: 1},
            "failed": False,
            "transfer_complete": False,
            "filename": "x.bin",
        }
        missing = self.receiver._check_for_missing_or_corrupt(transfer_id)
        self.assertEqual(missing, set())
        self.assertNotIn(transfer_id, self.receiver.active_transfers)


if __name__ == "__main__":
    unittest.main()
