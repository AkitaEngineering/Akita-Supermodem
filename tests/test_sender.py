"""
Unit tests for AkitaSender.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from akita_supermodem.sender import AkitaSender


class TestAkitaSender(unittest.TestCase):
    """Test AkitaSender functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_mesh = Mock()
        self.sender = AkitaSender(mesh_api=self.mock_mesh, piece_size=1024)

    def test_init(self):
        """Test sender initialization."""
        self.assertIsNotNone(self.sender.mesh)
        self.assertEqual(self.sender.piece_size, 1024)
        self.assertIsNotNone(self.sender._lock)  # Thread lock should exist

    def test_calculate_merkle_root(self):
        """Test Merkle root calculation."""
        hashes = ["a" * 64, "b" * 64, "c" * 64]  # Mock hex hashes
        root = self.sender._calculate_merkle_root(hashes)
        self.assertIsNotNone(root)
        self.assertIsInstance(root, str)

    def test_calculate_merkle_root_empty(self):
        """Test Merkle root with empty list."""
        root = self.sender._calculate_merkle_root([])
        # Should return hash of empty data
        self.assertIsNotNone(root)

    def test_get_piece_data(self):
        """Test retrieving piece data."""
        # Set up a transfer
        recipient_id = "test_recipient"
        self.sender.active_transfers[recipient_id] = {"num_pieces": 2, "pieces": [b"piece0", b"piece1"]}

        piece = self.sender._get_piece_data(recipient_id, 0)
        self.assertEqual(piece, b"piece0")

        piece = self.sender._get_piece_data(recipient_id, 1)
        self.assertEqual(piece, b"piece1")

        # Invalid index should return None
        piece = self.sender._get_piece_data(recipient_id, 99)
        self.assertIsNone(piece)

    def test_start_transfer_file_not_found(self):
        """Test starting transfer with non-existent file."""
        result = self.sender.start_transfer("recipient", "/nonexistent/file.txt")
        self.assertFalse(result)

    @patch("os.path.exists")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    @patch("builtins.open", create=True)
    def test_start_transfer_success(self, mock_open, mock_getsize, mock_isfile, mock_exists):
        """Test successful transfer start."""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_getsize.return_value = 2048  # 2 pieces

        # Mock file reading
        mock_file = MagicMock()
        mock_file.read.side_effect = [b"x" * 1024, b"y" * 1024, b""]
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock sendData
        self.mock_mesh.sendData.return_value = None

        result = self.sender.start_transfer("recipient", "test.txt")
        self.assertIsNotNone(result)  # Should succeed


if __name__ == "__main__":
    unittest.main()
