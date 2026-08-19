import time

from akita_supermodem.common import AKITA_CONTENT_TYPE
from akita_supermodem.generated import akita_pb2


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


class DropOnceMesh(FakeMesh):
    def __init__(self, node_id, drop_destination=None, drop_sequence=None):
        super().__init__(node_id)
        self.drop_destination = drop_destination
        self.drop_sequence = drop_sequence
        self.dropped = False

    def sendData(self, destinationId, payload, portNum):
        if portNum == AKITA_CONTENT_TYPE and not self.dropped:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            if (
                destinationId == self.drop_destination
                and msg.HasField("encrypted_payload")
                and msg.encrypted_payload.sequence == self.drop_sequence
            ):
                self.sent_payloads.append((destinationId, payload))
                self.dropped = True
                return
        super().sendData(destinationId, payload, portNum)


def wait_for_transfer(*managers, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for manager in managers:
            manager.check_timeouts()
        statuses = [status for manager in managers for status in manager.get_status()]
        if statuses and all(status.get("complete") or status.get("failed") for status in statuses):
            return statuses
        time.sleep(0.02)
    return [status for manager in managers for status in manager.get_status()]
