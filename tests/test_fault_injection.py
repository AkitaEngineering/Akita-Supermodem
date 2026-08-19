import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from akita_supermodem.common import AKITA_CONTENT_TYPE
from akita_supermodem.generated import akita_pb2
from akita_supermodem.transfer_manager import TransferManager

from tests.fakes import FakeMesh, wait_for_transfer


class CorruptOnceMesh(FakeMesh):
    def __init__(self, node_id, corrupt_sequence=1):
        super().__init__(node_id)
        self.corrupt_sequence = corrupt_sequence
        self.corrupted = False

    def sendData(self, destinationId, payload, portNum):
        if portNum == AKITA_CONTENT_TYPE and not self.corrupted:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            if (
                msg.HasField("encrypted_payload")
                and msg.encrypted_payload.sequence == self.corrupt_sequence
            ):
                damaged = bytearray(payload)
                damaged[-1] ^= 0xFF
                self.corrupted = True
                self.sent_payloads.append((destinationId, bytes(damaged)))
                recipient = FakeMesh.registry[destinationId]
                recipient.manager.handle_incoming_message(self.node_id, bytes(damaged))
                return
        super().sendData(destinationId, payload, portNum)


class HoldAfterMesh(FakeMesh):
    def __init__(self, node_id, hold_after=2):
        super().__init__(node_id)
        self.hold_after = hold_after
        self.encrypted_count = 0
        self.holding = False
        self.released = False
        self.queue = []

    def sendData(self, destinationId, payload, portNum):
        if portNum == AKITA_CONTENT_TYPE:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            if msg.HasField("encrypted_payload"):
                self.encrypted_count += 1
                if not self.released and self.encrypted_count > self.hold_after:
                    self.holding = True
                if self.holding:
                    self.queue.append((destinationId, payload, portNum))
                    return
        super().sendData(destinationId, payload, portNum)

    def release(self):
        self.holding = False
        self.released = True
        queued = list(self.queue)
        self.queue.clear()
        for destination_id, payload, port_num in queued:
            super().sendData(destination_id, payload, port_num)


class HoldMesh(FakeMesh):
    def __init__(self, node_id):
        super().__init__(node_id)
        self.holding = False
        self.queue = []

    def sendData(self, destinationId, payload, portNum):
        if self.holding:
            self.queue.append((destinationId, payload, portNum))
            return
        super().sendData(destinationId, payload, portNum)

    def release(self):
        self.holding = False
        queued = list(self.queue)
        self.queue.clear()
        for destination_id, payload, port_num in queued:
            super().sendData(destination_id, payload, port_num)


class TestFaultInjection(unittest.TestCase):
    def setUp(self):
        FakeMesh.registry = {}

    def tearDown(self):
        for mesh in list(FakeMesh.registry.values()):
            if mesh.manager:
                mesh.manager.close()

    def _pair(self, sender_mesh=None, receiver_mesh=None, **receiver_kwargs):
        sender_mesh = sender_mesh or FakeMesh("!sender")
        receiver_mesh = receiver_mesh or FakeMesh("!receiver")
        received = {}
        sender = TransferManager(sender_mesh, save_function=lambda _n, _d: None, profile_name="uas")
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda name, data: received.setdefault(name, data),
            profile_name="uas",
            **receiver_kwargs,
        )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        receiver.profile.timeout = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver
        return sender, receiver, received, sender_mesh, receiver_mesh

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_corrupt_encrypted_payload_recovers(self):
        sender, receiver, received, sender_mesh, _receiver_mesh = self._pair(
            sender_mesh=CorruptOnceMesh("!sender", corrupt_sequence=1)
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            payload = b"corrupt-recovery" * 40
            source.write_bytes(payload)
            sender.start_transfer("!receiver", str(source))
            wait_for_transfer(sender, receiver)

        self.assertTrue(sender_mesh.corrupted)
        self.assertEqual(received, {"flight-log.bin": payload})
        self.assertTrue(sender.get_status()[0]["complete"])
        self.assertTrue(receiver.get_status()[0]["complete"])
        self.assertFalse(receiver.get_status()[0]["failed"])

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_long_outage_then_resume(self):
        sender_mesh = HoldMesh("!sender")
        sender, receiver, received, sender_mesh, _receiver_mesh = self._pair(sender_mesh=sender_mesh)
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            payload = b"outage-payload" * 40
            source.write_bytes(payload)
            sender.start_transfer("!receiver", str(source))
            sender_mesh.holding = True
            time.sleep(0.05)
            sender_mesh.release()
            wait_for_transfer(sender, receiver)

        self.assertEqual(received, {"flight-log.bin": payload})
        self.assertTrue(sender.get_status()[0]["complete"])

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_receiver_process_restart_resumes_checkpoint(self):
        checkpoint_dir = os.environ["AKITA_CHECKPOINT_DIR"]
        sender_mesh = HoldAfterMesh("!sender", hold_after=2)
        sender, receiver, received, sender_mesh, receiver_mesh = self._pair(sender_mesh=sender_mesh)
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "flight-log.bin"
            payload = b"restart-resume" * 48
            source.write_bytes(payload)
            sender.start_transfer("!receiver", str(source))

            deadline = time.time() + 2.0
            while time.time() < deadline:
                status = receiver.get_status()
                if status and status[0].get("received_pieces", 0) >= 1 and not status[0].get("complete"):
                    break
                time.sleep(0.01)
            else:
                self.fail("Receiver never accepted a piece before restart")

            receiver.close()
            restarted_received = {}
            restarted = TransferManager(
                receiver_mesh,
                save_function=lambda name, data: restarted_received.setdefault(name, data),
                profile_name="uas",
                checkpoint_dir=checkpoint_dir,
            )
            restarted.profile.initial_delay = 0.0
            receiver_mesh.manager = restarted
            for destination, packet in reversed(sender_mesh.sent_payloads):
                msg = akita_pb2.AkitaMessage()
                msg.ParseFromString(packet)
                if destination == "!receiver" and msg.HasField("encrypted_payload"):
                    restarted.handle_incoming_message("!sender", packet)
                    break
            sender_mesh.release()
            sender_handler = next(
                handler for handler in sender.handlers.values() if hasattr(handler, "_send_pieces")
            )
            sender_handler._send_pieces([0, 1, 2, 3, 4, 5])
            wait_for_transfer(sender, restarted, timeout=4.0)
            self.assertEqual(restarted_received, {"flight-log.bin": payload})
        self.assertEqual(received, {})
        self.assertTrue(sender.get_status()[0]["complete"])
        self.assertTrue(restarted.get_status()[0]["complete"])
        restarted.close()

    @patch.dict(os.environ, {"AKITA_SUPERMODEM_PSK": "test-shared-secret"})
    def test_soak_multiple_sequential_files(self):
        sender_mesh = FakeMesh("!sender")
        receiver_mesh = FakeMesh("!receiver")
        received = {}
        sender = TransferManager(sender_mesh, save_function=lambda _n, _d: None, profile_name="uas")
        receiver = TransferManager(
            receiver_mesh,
            save_function=lambda name, data: received.__setitem__(name, data),
            profile_name="uas",
        )
        sender.profile.initial_delay = 0.0
        receiver.profile.initial_delay = 0.0
        sender_mesh.manager = sender
        receiver_mesh.manager = receiver

        expected = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            for index in range(5):
                received.clear()
                source = Path(temp_dir) / f"soak-{index}.bin"
                payload = f"soak-file-{index}-".encode() * 20
                source.write_bytes(payload)
                sender.start_transfer("!receiver", str(source))
                wait_for_transfer(sender, receiver)
                self.assertEqual(received.get(f"soak-{index}.bin"), payload)
                expected[f"soak-{index}.bin"] = payload
                sender.close()
                # Keep one live receiver; sender needs a fresh session manager.
                sender = TransferManager(sender_mesh, save_function=lambda _n, _d: None, profile_name="uas")
                sender.profile.initial_delay = 0.0
                sender_mesh.manager = sender

        self.assertEqual(len(expected), 5)


if __name__ == "__main__":
    unittest.main()
