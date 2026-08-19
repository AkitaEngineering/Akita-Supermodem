import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from akita_supermodem.common import publish_file
from akita_supermodem.config import get_profile
from akita_supermodem.generated import akita_pb2
from akita_supermodem.transfer_manager import TransferManager
from tests.fakes import DropOnceMesh, FakeMesh, wait_for_transfer


class TestTransferManager(unittest.TestCase):
    def setUp(self):
        FakeMesh.registry = {}

    def tearDown(self):
        # Ensure send workers do not leak into later tests.
        for mesh in list(FakeMesh.registry.values()):
            if mesh.manager:
                mesh.manager.close()

    @patch.dict(os.environ, {}, clear=True)
    def test_uas_profile_requires_psk(self):
        mesh = FakeMesh("!sender")
        with self.assertRaises(ValueError):
            TransferManager(mesh, save_function=lambda _name, _data: None, profile_name="uas")

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "too-short"}, clear=True)
    def test_short_psk_is_rejected(self):
        mesh = FakeMesh("!sender")
        with self.assertRaises(ValueError):
            TransferManager(mesh, save_function=lambda _name, _data: None, profile_name="uas")

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            get_profile("typo-profile")

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
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
            wait_for_transfer(sender, receiver)

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

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_empty_file_transfer_completes(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        received = {}
        sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda name, data: received.setdefault(name, data),
            profile_name="uas",
        )
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "empty.bin"
            source.write_bytes(b"")
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(sender, receiver)
        self.assertEqual(received, {"empty.bin": b""})
        self.assertTrue(sender.get_status()[0]["complete"])
        self.assertTrue(receiver.get_status()[0]["complete"])

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
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
            wait_for_transfer(sender, receiver)

        replay_payload = None
        for destination, payload in sender_mesh.sent_payloads:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            if destination == "!receiver" and msg.HasField("encrypted_payload"):
                replay_payload = payload
                break

        self.assertIsNotNone(replay_payload)
        before = set(receiver.received_sequences[session_id].seen)
        receiver.handle_incoming_message("!sender", replay_payload)

        self.assertEqual(len(received), 1)
        self.assertEqual(before, receiver.received_sequences[session_id].seen)

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_duplicate_key_exchange_does_not_crash(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        receiver = TransferManager(receiver_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            source.write_bytes(b"abc123" * 40)
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(sender, receiver)

        reply = None
        for destination, payload in receiver_mesh.sent_payloads:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            if destination == "!sender" and msg.HasField("key_exchange"):
                reply = payload
                break
        self.assertIsNotNone(reply)
        sender.handle_incoming_message("!receiver", reply)
        self.assertTrue(sender.get_status()[0]["complete"])

    def test_mismatched_psk_cannot_complete_transfer(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        received = []

        with patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "sender-secret-key!!"}, clear=True):
            sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        with patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "receiver-secret-key"}, clear=True):
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
            time.sleep(0.1)
            receiver.check_timeouts()

        self.assertEqual(received, [])
        self.assertFalse(any(status.get("complete") for status in sender.get_status()))
        self.assertFalse(any(status.get("complete") for status in receiver.get_status()))

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_receive_can_publish_staged_file_by_path(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        bytes_save_calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "saved.bin"

            def save_path(name, source_path):
                self.assertEqual(name, "flight-log.bin")
                publish_file(source_path, output)

            sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
            receiver = TransferManager(
                receiver_mesh,
                save_function=lambda name, data: bytes_save_calls.append((name, data)),
                save_path_function=save_path,
                profile_name="uas",
            )
            sender.profile.initial_delay = 0.0
            receiver.profile.initial_delay = 0.0
            sender_mesh.manager = sender
            receiver_mesh.manager = receiver

            source = Path(temp_dir) / "flight-log.bin"
            payload = b"path-save-payload" * 20
            source.write_bytes(payload)
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(sender, receiver)

            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(bytes_save_calls, [])

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_save_failure_marks_transfer_failed(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")

        def boom(_name, _path):
            raise OSError("disk full")

        sender = TransferManager(sender_mesh, save_function=lambda _name, _data: None, profile_name="uas")
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda _name, _data: None,
            save_path_function=boom,
            profile_name="uas",
        )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            source.write_bytes(b"payload-bytes" * 20)
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(receiver)

        receiver_status = receiver.get_status()[0]
        self.assertTrue(receiver_status["failed"])
        self.assertFalse(receiver_status["complete"])
        self.assertEqual(receiver_status["error"], "save_failed")

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_mtu_guard_rejects_oversized_profile_piece(self):
        mesh = FakeMesh("!sender")
        manager = TransferManager(mesh, save_function=lambda _name, _data: None, profile_name="uas")
        manager.profile.piece_size = 1024
        manager.profile.max_payload_bytes = 256
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "too-large.bin"
            source.write_bytes(b"x" * 64)
            with self.assertRaises(ValueError):
                manager.start_transfer("!receiver", str(source))

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_events_are_emitted_for_transfer_progress(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        events = []

        sender = TransferManager(
            sender_mesh,
            save_function=lambda _name, _data: None,
            profile_name="uas",
            event_callback=events.append,
        )
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda _name, _data: None,
            profile_name="uas",
            event_callback=events.append,
        )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            source.write_bytes(b"event-payload" * 20)
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(sender, receiver)

        event_names = {event["event"] for event in events}
        self.assertIn("handshake_started", event_names)
        self.assertIn("handshake_complete", event_names)
        self.assertIn("piece_sent", event_names)
        self.assertIn("piece_received", event_names)
        self.assertIn("transfer_complete", event_names)

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_dropped_piece_recovers_with_resume_request(self):
        sender_mesh = DropOnceMesh("!sender", drop_destination="!receiver", drop_sequence=1)
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
        receiver.profile.timeout = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            payload = b"resume-me" * 64
            source.write_bytes(payload)
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(sender, receiver)

        self.assertTrue(sender_mesh.dropped)
        self.assertEqual(received, {"flight-log.bin": payload})
        self.assertTrue(sender.get_status()[0]["complete"])


if __name__ == "__main__":
    unittest.main()
