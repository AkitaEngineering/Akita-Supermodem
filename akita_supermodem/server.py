import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from .common import AKITA_CONTENT_TYPE, MAX_PIECE_SIZE, MIN_PIECE_SIZE, sanitize_filename
from .generated import akita_pb2
from .receiver import AkitaReceiver
from .sender import AkitaSender
from .settings import settings

app = FastAPI(title="Akita Supermodem UI")
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"


class ConfigUpdate(BaseModel):
    key: str
    value: Any


class MeshConnectRequest(BaseModel):
    device: Optional[str] = None


class TransferSendRequest(BaseModel):
    filepath: str
    recipient_id: Optional[str] = None
    piece_size: Optional[int] = None


class RuntimeState:
    def __init__(self):
        self.mesh = None
        self.sender: Optional[AkitaSender] = None
        self.receiver: Optional[AkitaReceiver] = None
        self.device: Optional[str] = None
        self._lock = threading.RLock()

    def connect(self, device: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self.mesh is not None:
                return {"connected": True, "device": self.device}

            try:
                import meshtastic.serial_interface
            except ImportError as e:
                raise HTTPException(status_code=503, detail=f"Meshtastic is not installed: {e}") from e

            try:
                self.mesh = (
                    meshtastic.serial_interface.SerialInterface(device=device)
                    if device
                    else meshtastic.serial_interface.SerialInterface()
                )
                self.device = device or "auto"
                self.sender = AkitaSender(mesh_api=self.mesh)
                self.receiver = AkitaReceiver(
                    save_function=self._save_received_file,
                    send_function=self._send_data,
                    request_interval=10.0,
                )
                self.mesh.add_on_receive(self._on_receive)
                return {"connected": True, "device": self.device}
            except Exception as e:
                self.mesh = None
                self.sender = None
                self.receiver = None
                self.device = None
                raise HTTPException(status_code=503, detail=f"Unable to connect to Meshtastic device: {e}") from e

    def disconnect(self) -> Dict[str, Any]:
        with self._lock:
            if self.mesh is not None:
                try:
                    self.mesh.close()
                except Exception as e:
                    logger.warning(f"Error while closing Meshtastic interface: {e}")
            self.mesh = None
            self.sender = None
            self.receiver = None
            self.device = None
        return {"connected": False}

    def start_transfer(self, request: TransferSendRequest) -> Dict[str, Any]:
        with self._lock:
            if self.mesh is None or self.sender is None:
                raise HTTPException(status_code=409, detail="Mesh interface is not connected.")
            recipient_id = request.recipient_id or settings.get("default_mesh_node")
            if not recipient_id:
                raise HTTPException(status_code=400, detail="recipient_id is required.")
            filepath = Path(request.filepath).expanduser()
            if not filepath.exists() or not filepath.is_file():
                raise HTTPException(status_code=400, detail="filepath must point to an existing file.")
            if request.piece_size:
                if not MIN_PIECE_SIZE <= request.piece_size <= MAX_PIECE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=f"piece_size must be between {MIN_PIECE_SIZE} and {MAX_PIECE_SIZE} bytes.",
                    )
                self.sender.piece_size = request.piece_size

            if not self.sender.start_transfer(recipient_id, str(filepath)):
                raise HTTPException(status_code=500, detail="Transfer could not be started.")
            return {"status": "started", "recipient_id": recipient_id, "filepath": str(filepath)}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            transfers = []
            if self.sender is not None:
                for recipient_id, transfer in self.sender.active_transfers.items():
                    sent = sum(1 for value in transfer.get("sent_pieces", []) if value)
                    acked = sum(1 for value in transfer.get("acknowledged_pieces", []) if value)
                    transfers.append(
                        {
                            "direction": "send",
                            "peer": recipient_id,
                            "filename": transfer.get("filename"),
                            "total_size": transfer.get("total_size", 0),
                            "piece_size": transfer.get("piece_size", 0),
                            "num_pieces": transfer.get("num_pieces", 0),
                            "sent_pieces": sent,
                            "acknowledged_pieces": acked,
                            "complete": bool(transfer.get("transfer_complete")),
                        }
                    )
            if self.receiver is not None:
                for transfer_id, transfer in self.receiver.active_transfers.items():
                    received = len(transfer.get("received_pieces", {}))
                    transfers.append(
                        {
                            "direction": "receive",
                            "peer": transfer.get("source_node", transfer_id),
                            "filename": transfer.get("filename"),
                            "total_size": transfer.get("total_size", 0),
                            "piece_size": transfer.get("piece_size", 0),
                            "num_pieces": transfer.get("num_pieces", 0),
                            "received_pieces": received,
                            "complete": bool(transfer.get("transfer_complete")),
                            "failed": bool(transfer.get("failed")),
                        }
                    )
            return {
                "mesh": {"connected": self.mesh is not None, "device": self.device},
                "transfers": transfers,
            }

    def _save_received_file(self, filename: str, data: bytes) -> None:
        save_dir = settings.config_file.parent / "received_files"
        save_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = sanitize_filename(filename)
        base, ext = os.path.splitext(safe_filename)
        filepath = save_dir / safe_filename
        counter = 1
        while filepath.exists():
            filepath = save_dir / f"{base}_{counter}{ext}"
            counter += 1
        filepath.write_bytes(data)

    def _send_data(self, node_id: str, payload: bytes, port_num: int) -> None:
        with self._lock:
            if self.mesh is None:
                raise RuntimeError("Mesh interface is not connected.")
            self.mesh.sendData(destinationId=node_id, payload=payload, portNum=port_num)

    def _on_receive(self, packet, interface) -> None:
        payload = packet.get("decoded", {}).get("payload")
        portnum = packet.get("decoded", {}).get("portnum")
        if not payload or portnum != AKITA_CONTENT_TYPE:
            return

        try:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
            sender_id = packet.get("fromId") or packet.get("from")
            if not sender_id:
                logger.warning("Ignoring Akita packet without sender id.")
                return
            is_broadcast = packet.get("to") == getattr(interface, "BROADCAST_ADDR", None)

            with self._lock:
                receiver = self.receiver
                sender = self.sender

            if msg.HasField("file_start") and receiver:
                receiver.handle_file_start(sender_id, msg.file_start, is_broadcast)
            elif msg.HasField("piece_data") and receiver:
                receiver.handle_piece_data(sender_id, msg.piece_data, is_broadcast)
            elif msg.HasField("resume_request") and sender:
                sender.handle_resume_request(sender_id, msg.resume_request)
        except Exception as e:
            logger.error(f"Error processing incoming Akita packet: {e}")


runtime = RuntimeState()


@app.get("/api/config")
def get_config():
    return settings.get_all()


@app.post("/api/config")
def update_config(update: ConfigUpdate):
    try:
        settings.set(update.key, update.value)
    except (KeyError, ValueError, TypeError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "success", "config": settings.get_all()}


@app.get("/api/status")
def get_status():
    return runtime.status()


@app.get("/api/transfers")
def get_transfers():
    return {"transfers": runtime.status()["transfers"]}


@app.post("/api/mesh/connect")
def connect_mesh(request: MeshConnectRequest):
    return runtime.connect(request.device)


@app.post("/api/mesh/disconnect")
def disconnect_mesh():
    return runtime.disconnect()


@app.post("/api/transfers/send")
def send_transfer(request: TransferSendRequest):
    return runtime.start_transfer(request)


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


def start_server():
    host = settings.get("ui_host", "127.0.0.1")
    port = int(settings.get("ui_port", 8080))
    logger.info(f"Starting Akita UI on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level=settings.get("log_level", "INFO").lower())
