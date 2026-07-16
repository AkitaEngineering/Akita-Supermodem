import tempfile
import unittest
from pathlib import Path

from akita_supermodem.artifact_signing import (
    generate_keypair,
    sign_bytes,
    verify_bytes,
    sign_file,
    verify_file,
)


class TestArtifactSigning(unittest.TestCase):
    def test_sign_and_verify_bytes(self):
        private_key, public_key = generate_keypair()
        data = b"mission-artifact"
        signature = sign_bytes(private_key, data)

        self.assertTrue(verify_bytes(public_key, data, signature))
        self.assertFalse(verify_bytes(public_key, data + b"-tampered", signature))

    def test_sign_and_verify_file(self):
        private_key, public_key = generate_keypair()
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "mission.json"
            artifact.write_bytes(b'{"mission":"survey"}')
            signature = sign_file(private_key, artifact)

            self.assertTrue(verify_file(public_key, artifact, signature))

            artifact.write_bytes(b'{"mission":"tampered"}')
            self.assertFalse(verify_file(public_key, artifact, signature))


if __name__ == "__main__":
    unittest.main()
