"""
Unit tests for common utilities.
"""

import unittest
from akita_supermodem.common import calculate_hash, sanitize_filename, calculate_merkle_root, HASH_ALGORITHM


class TestCommon(unittest.TestCase):
    """Test common utility functions."""

    def test_calculate_hash(self):
        """Test hash calculation."""
        data = b"test data"
        hash_result = calculate_hash(data)
        
        # Should return a hex string
        self.assertIsInstance(hash_result, str)
        self.assertEqual(len(hash_result), 64)  # SHA256 produces 64 hex chars
        
        # Should be deterministic
        hash2 = calculate_hash(data)
        self.assertEqual(hash_result, hash2)
        
        # Different data should produce different hash
        hash3 = calculate_hash(b"different data")
        self.assertNotEqual(hash_result, hash3)

    def test_calculate_hash_empty(self):
        """Test hash calculation with empty data."""
        hash_result = calculate_hash(b"")
        self.assertIsInstance(hash_result, str)
        self.assertEqual(len(hash_result), 64)

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        # Normal filename should pass through (mostly)
        safe = sanitize_filename("test.txt")
        self.assertIn("test", safe)
        self.assertIn(".txt", safe)
        
        # Path traversal should be removed
        unsafe = "../../etc/passwd"
        safe = sanitize_filename(unsafe)
        self.assertNotIn("../", safe)
        self.assertNotIn("/", safe)
        
        # Empty filename should get default
        safe = sanitize_filename("")
        self.assertEqual(safe, "unnamed_file")
        
        # Just dots should get default
        safe = sanitize_filename("...")
        self.assertEqual(safe, "unnamed_file")
        
        # Dangerous characters should be removed
        safe = sanitize_filename("file<script>.txt")
        self.assertNotIn("<", safe)
        self.assertNotIn(">", safe)

    def test_sanitize_filename_length(self):
        """Test that very long filenames are truncated."""
        long_name = "a" * 300 + ".txt"
        safe = sanitize_filename(long_name)
        self.assertLessEqual(len(safe), 255)
    
    def test_calculate_merkle_root(self):
        """Test Merkle root calculation."""
        # Test with empty list
        result = calculate_merkle_root([])
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 64)  # SHA256 hex string length
        
        # Test with single hash
        hash1 = calculate_hash(b"test1")
        result = calculate_merkle_root([hash1])
        self.assertEqual(result, hash1)
        
        # Test with two hashes
        hash2 = calculate_hash(b"test2")
        result = calculate_merkle_root([hash1, hash2])
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 64)
        # Should be different from individual hashes
        self.assertNotEqual(result, hash1)
        self.assertNotEqual(result, hash2)
        
        # Test with three hashes (odd number)
        hash3 = calculate_hash(b"test3")
        result = calculate_merkle_root([hash1, hash2, hash3])
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 64)
        
        # Test with invalid hex string
        result = calculate_merkle_root(["invalid_hex"])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

