import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from akita_supermodem.common import AKITA_CONTENT_TYPE
from akita_supermodem.generated import akita_pb2
from akita_supermodem.transfer_manager import TransferManager


class FakeMesh:
    registry = {}

    def __init__(self, node_id):
        self.node_id = node_id
        self.manager = None
        self.sent_payloads = []
        FakeMesh.registry[node_id] = self

    def sendData(self, destinationId, payload, portNum):
        if portNum != AKITA_CONTENT_TYPE:
            return
        self.sent_payloads.append((destinationId, payload))
        recipient = FakeMesh.registry[destinationId]
        recipient.manager.handle_incoming_message(self.node_id, payload)


class TestTransferManager(unittest.TestCase):
    def setUp(self):
        FakeMesh.registry = {}

    @patch.dict(os.environ, {}, clear=True)
    def test_uas_profile_requires_psk(self):
        mesh = FakeMesh("!sender")
        with self.assertRaises(ValueError):
            TransferManager(mesh, save_function=lambda _name, _data: None, profile_name="uas")

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"}, clear=True)
    def test_encrypted_psk_transfer_completes_over_fake_mesh(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        received = {}

        sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda name, data: received.setdefault(name, data),
            profile_name="uas",
        )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            payload = b"uav-log-data" * 32
            source.write_bytes(payload)

            session_id = sender.start_transfer("!receiver", str(source))

        sender_status = sender.get_status()[0]
        receiver_status = receiver.get_status()[0]

        self.assertEqual(received, {"flight-log.bin": payload})
        self.assertEqual(sender_status["session_id"], session_id)
        self.assertTrue(sender_status["encrypted"])
        self.assertTrue(sender_status["authenticated"])
        self.assertTrue(sender_status["complete"])
        self.assertFalse(sender_status["failed"])
        self.assertTrue(receiver_status["complete"])
        self.assertFalse(receiver_status["failed"])
        self.assertGreater(sender_status["compressed_pieces"], 0)
        self.assertLess(sender_status["wire_data_bytes"], sender_status["plain_data_bytes"])

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"}, clear=True)
    def test_replayed_encrypted_payload_is_rejected(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        received = []

        sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda name, data: received.append((name, data)),
            profile_name="uas",
        )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            source.write_bytes(b"abc123" * 80)
            session_id = sender.start_transfer("!receiver", str(source))

        replay_payload = None
        for destination, payload in sender_mesh.sent_payloads:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            if destination == "!receiver" and msg.HasField("encrypted_payload"):
                replay_payload = payload
                break

        self.assertIsNotNone(replay_payload)
        before = set(receiver.received_sequences[session_id])
        receiver.handle_incoming_message("!sender", replay_payload)

        self.assertEqual(len(received), 1)
        self.assertEqual(before, receiver.received_sequences[session_id])

    def test_mismatched_psk_cannot_complete_transfer(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        received = []

        with patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "sender-secret"}, clear=True):
            sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        with patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "receiver-secret"}, clear=True):
            receiver = TransferManager(
                receiver_mesh,
                save_function=lambda name, data: received.append((name, data)),
                profile_name="uas",
            )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            source.write_bytes(b"secret-flight-log")
            sender.start_transfer("!receiver", str(source))

        self.assertEqual(received, [])
        self.assertFalse(any(status.get("complete") for status in sender.get_status()))
        self.assertTrue(any(status.get("failed") for status in receiver.get_status()))


if __name__ == "__main__":
    unittest.main()
