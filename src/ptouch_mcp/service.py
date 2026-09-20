"""HTTP API and MCP server.

One FastAPI app serves both: plain REST for Home Assistant's `rest_command`, and a
Streamable HTTP MCP endpoint at /mcp for Claude and other MCP clients.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from mcp.server.mcpserver import MCPServer, Image as MCPImage
from pydantic import BaseModel, Field

from .config import Config
from .labels import LabelError
from .printer import PrinterError, make_backend

log = logging.getLogger(__name__)

cfg = Config.from_env()
backend = make_backend(cfg)


class LabelRequest(BaseModel):
    text: str = Field(min_length=1)
    copies: int = 1
    tape_mm: float | None = None
    align: str = "center"


def _validate(text: str, copies: int) -> None:
    if len(text) > cfg.max_text:
        raise LabelError(f"text must be {cfg.max_text} characters or fewer")
    if copies < 1:
        raise LabelError("copies must be at least 1")
    if copies > cfg.max_copies:
        raise LabelError(f"copies must be {cfg.max_copies} or fewer (asked for {copies})")


def do_print(text: str, copies: int = 1, tape_mm: float | None = None, align: str = "center") -> dict:
    _validate(text, copies)
    result = backend.print(text, copies=copies, tape_mm=tape_mm, align=align)
    return {**result.as_dict(), "text": text}


def do_render(text: str, tape_mm: float | None = None, align: str = "center"):
    _validate(text, 1)
    built = backend.build(text, tape_mm, align)
    w, h = built.size_mm
    meta = {
        "tape_mm": built.tape_mm,
        "width_px": built.label.image.width,
        "height_px": built.label.image.height,
        "size_mm": [round(w, 1), round(h, 1)],
    }
    return built.png(), meta


# --- MCP ------------------------------------------------------------------
# Keep these descriptions short. An MCP client resends every tool's schema on every
# request, so verbose tool definitions are a tax on each utterance -- which adds up
# fast on a voice assistant.

mcp = MCPServer("ptouch", version="0.1.0")


@mcp.tool()
def print_label(text: str, copies: int = 1, tape_mm: float | None = None) -> dict:
    """Print a label on the Brother P-touch. Newlines make multiple lines."""
    try:
        return do_print(text, copies=copies, tape_mm=tape_mm)
    except (LabelError, PrinterError) as exc:
        return {"error": str(exc)}


@mcp.tool()
def preview_label(text: str, tape_mm: float | None = None) -> MCPImage:
    """Show what a label would look like without printing it."""
    png, _ = do_render(text, tape_mm=tape_mm)
    return MCPImage(data=png, format="png")


@mcp.tool()
def printer_status() -> dict:
    """Whether the printer is reachable and what tape it expects."""
    return backend.status().as_dict()


# --- HTTP -----------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "ptouch-mcp starting: model=%s backend=%s transport=%s tape=%smm",
        cfg.model, cfg.backend, cfg.transport, cfg.tape_mm,
    )
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="ptouch-mcp", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/status")
def status() -> dict:
    return backend.status().as_dict()


@app.post("/print")
def print_endpoint(req: LabelRequest) -> dict:
    try:
        return do_print(req.text, copies=req.copies, tape_mm=req.tape_mm, align=req.align)
    except LabelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PrinterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/preview")
def preview_endpoint(req: LabelRequest) -> Response:
    """PNG of the label. Metadata rides along in X-Label-* headers."""
    try:
        png, meta = do_render(req.text, tape_mm=req.tape_mm, align=req.align)
    except LabelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Label-Tape-Mm": str(meta["tape_mm"]),
            "X-Label-Size-Px": f"{meta['width_px']}x{meta['height_px']}",
            "X-Label-Size-Mm": f"{meta['size_mm'][0]}x{meta['size_mm'][1]}",
        },
    )


# stateless_http keeps each call self-contained -- no session to expire between a
# voice command now and the next one an hour later.
app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/", stateless_http=True))
