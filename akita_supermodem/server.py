from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import uvicorn
from .settings import settings

app = FastAPI(title="Akita Supermodem UI")

WEB_DIR = Path(__file__).parent / "web"

# Ensure web dir exists
WEB_DIR.mkdir(parents=True, exist_ok=True)


class ConfigUpdate(BaseModel):
    key: str
    value: str


@app.get("/api/config")
def get_config():
    return settings.get_all()


@app.post("/api/config")
def update_config(update: ConfigUpdate):
    settings.set(update.key, update.value)
    return {"status": "success"}


@app.get("/api/status")
def get_status():
    # Placeholder for live transfer status
    return {"transfers": []}


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


def start_server():
    host = settings.get("ui_host", "127.0.0.1")
    port = int(settings.get("ui_port", 8080))
    print(f"Starting Akita UI on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="error")
