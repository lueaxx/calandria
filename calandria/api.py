"""HTTP and WebSocket surface.

Three audiences share one server:

  * the **audience**, who open a page, pick a stage and a language, and read;
  * the **stream**, which loads the overlay as a browser source in OBS or vMix;
  * the **production team**, who watch the dashboard and want to know about
    trouble before the speaker does.

Each is a static page with no build step. That is a deliberate constraint: an
operator deploying this at 8am on the first day of a conference should not need
a Node toolchain, and a judge evaluating it should not need one either.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .bus import Bus, create_bus
from .config import Config, SessionConfig
from .events import TOPIC_STATUS, topic_captions
from .export import FORMATS, MEDIA_TYPES
from .orchestrator import Orchestrator
from .translate.gemini import language_name

log = logging.getLogger("calandria.api")
WEB = Path(__file__).parent / "web"


def create_app(cfg: Config) -> FastAPI:
    bus: Bus = create_bus(cfg.bus, history=cfg.features.catchup_buffer or 1)
    orch = Orchestrator(cfg, bus)
    app = FastAPI(title="Calandria", version="1.0.0", docs_url="/api/docs")
    app.state.cfg = cfg
    app.state.bus = bus
    app.state.orch = orch

    @app.on_event("startup")
    async def _startup():
        await orch.start_all()
        log.info("Calandria ready on http://%s:%s", cfg.server.host, cfg.server.port)

    @app.on_event("shutdown")
    async def _shutdown():
        await orch.stop_all()
        await bus.close()

    # ------------------------------------------------------------------- pages

    def _page(name: str, enabled: bool):
        if not enabled:
            raise HTTPException(404, "this feature is disabled in the configuration")
        return FileResponse(WEB / name)

    @app.get("/", include_in_schema=False)
    async def viewer():
        return _page("viewer.html", cfg.features.viewer)

    @app.get("/overlay", include_in_schema=False)
    async def overlay():
        return _page("overlay.html", cfg.features.overlay)

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        return _page("dashboard.html", cfg.features.dashboard)

    @app.get("/capture", include_in_schema=False)
    async def capture():
        """Send a stage's audio from the laptop already plugged into the desk.

        The simplest deployment there is: no encoder, no RTMP server, nothing
        to install, and no CDN between the microphone and the model -- which is
        what keeps the latency the rest of this system is built for.
        """
        return _page("capture.html", cfg.features.capture)

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    # --------------------------------------------------------------------- api

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, **orch.totals()}

    @app.get("/api/config")
    async def api_config():
        """What the front-end needs to render itself. No secrets here."""
        return {
            "features": cfg.features.model_dump(),
            "backend": cfg.stt.backend,
            "sessions": [
                {
                    "id": w.cfg.id,
                    "title": w.cfg.title,
                    "source_language": w.cfg.source_language,
                    "languages": [w.cfg.source_language, *w.cfg.targets],
                    "state": w.status.state.value,
                }
                for w in orch.workers.values()
            ],
            "language_names": {
                code: language_name(code)
                for w in orch.workers.values()
                for code in (w.cfg.source_language, *w.cfg.targets)
            },
        }

    @app.get("/api/sessions")
    async def list_sessions():
        return {"sessions": orch.statuses(), "totals": orch.totals()}

    @app.post("/api/sessions", status_code=201)
    async def create_session(payload: dict):
        try:
            session_cfg = SessionConfig.model_validate(payload)
            worker = orch.add(session_cfg)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await worker.start()
        return worker.status.to_dict()

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if session_id not in orch.workers:
            raise HTTPException(404, "no such session")
        await orch.remove(session_id)
        return {"removed": session_id}

    @app.post("/api/sessions/{session_id}/{action}")
    async def control(session_id: str, action: str):
        worker = orch.workers.get(session_id)
        if not worker:
            raise HTTPException(404, "no such session")
        if action == "start":
            await worker.start()
        elif action == "stop":
            await worker.stop()
        else:
            raise HTTPException(400, "action must be 'start' or 'stop'")
        return worker.status.to_dict()

    @app.get("/api/sessions/{session_id}/projection")
    async def projection(
        session_id: str,
        stages: int = Query(10, ge=1, le=200),
        hours: float = Query(10, gt=0, le=200),
    ):
        """Extrapolate this session's measured spend to a whole conference."""
        worker = orch.workers.get(session_id)
        if not worker:
            raise HTTPException(404, "no such session")
        return worker.cost.project(stages, hours, len(worker.cfg.targets))

    @app.get("/api/sessions/{session_id}/transcript.{fmt}")
    async def transcript(session_id: str, fmt: str, lang: str | None = None):
        if not cfg.features.export:
            raise HTTPException(404, "export is disabled in the configuration")
        worker = orch.workers.get(session_id)
        if not worker:
            raise HTTPException(404, "no such session")
        lang = lang or worker.cfg.source_language
        items = worker.finals.get(lang, [])
        if fmt == "json":
            return JSONResponse(items)
        if fmt not in FORMATS:
            raise HTTPException(400, f"format must be one of: {', '.join(FORMATS)}, json")
        body = FORMATS[fmt](items)
        return Response(
            content=body,
            media_type=MEDIA_TYPES[fmt],
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.{lang}.{fmt}"'
            },
        )

    # -------------------------------------------------------------- websockets

    @app.websocket("/ws/captions")
    async def ws_captions(
        ws: WebSocket,
        session: str = Query(...),
        lang: str = Query(...),
        replay: int = Query(0, ge=0, le=500),
    ):
        await ws.accept()
        if session not in orch.workers:
            await ws.close(code=4404, reason="no such session")
            return
        limit = min(replay, cfg.features.catchup_buffer)
        try:
            async for msg in bus.subscribe(topic_captions(session, lang), replay=limit):
                if "__closed__" in msg:
                    break
                await ws.send_text(json.dumps(msg))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            log.debug("caption socket closed: %s", exc)

    @app.websocket("/ws/status")
    async def ws_status(ws: WebSocket):
        await ws.accept()
        try:
            await ws.send_text(json.dumps({"snapshot": orch.statuses(),
                                           "totals": orch.totals()}))
            async for msg in bus.subscribe(TOPIC_STATUS):
                if "__closed__" in msg:
                    break
                await ws.send_text(json.dumps({"status": msg, "totals": orch.totals()}))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            log.debug("status socket closed: %s", exc)

    # One microphone per stage. Two sockets pushing into the same session
    # interleave two copies of the room into one stream, and the model does not
    # report that as an error -- it just degrades, which is far harder to
    # diagnose than a refusal. Observed live: a second capture tab left open
    # pushed transcription latency from ~1 s to 8 s and then stopped it
    # entirely, with every counter still reading healthy.
    active_ingest: dict[str, WebSocket] = {}

    @app.websocket("/ws/ingest")
    async def ws_ingest(ws: WebSocket, session: str = Query(...)):
        """Accept raw PCM from a browser or an on-stage agent.

        Expects 16 kHz mono 16-bit little-endian frames as binary messages --
        the same format everything else in the pipeline speaks.
        """
        await ws.accept()
        worker = orch.workers.get(session)
        if not worker:
            await ws.close(code=4404, reason="no such session")
            return
        source = worker.push_source
        if source is None:
            await ws.close(code=4400, reason="this session is not configured with source.type=mic")
            return

        # The newest connection wins. The alternative -- refuse the newcomer --
        # reads as safer but fails the case that actually happens at an event:
        # the operator's laptop drops its WiFi and reconnects, and a half-dead
        # socket the server has not timed out yet would keep the stage silent.
        previous = active_ingest.get(session)
        if previous is not None:
            log.warning(
                "[%s] a second audio source connected; dropping the first. "
                "Two sockets feeding one stage mixes both into the transcript.",
                session,
            )
            with contextlib.suppress(Exception):
                await previous.close(code=4409, reason="replaced by a newer audio source")
        active_ingest[session] = ws

        try:
            while True:
                source.push(await ws.receive_bytes())
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            log.debug("ingest socket closed: %s", exc)
        finally:
            # Only clear the slot if it is still ours: a newer socket may have
            # taken over already, and removing its entry would let a third
            # connection in without displacing it.
            if active_ingest.get(session) is ws:
                active_ingest.pop(session, None)

    return app


def serve(cfg: Config) -> None:
    import uvicorn

    uvicorn.run(
        create_app(cfg),
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
