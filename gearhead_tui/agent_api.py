"""REST API for agents / programmatic drivers.

Same shape as brogue-tui / simcity-tui: an aiohttp server running on
the same asyncio loop as Textual, exposing a narrow surface:

  GET  /health          — {"ok": true, "running": bool, "serial": int}
  GET  /state           — {"running", "serial", "cursor", "message"}
  GET  /snapshot        — the full parsed grid as JSON rows
  POST /key {"k": "..."}— forward a keystroke or named key

The server returns control to Textual immediately; each handler reads
engine state via its thread-safe accessors. No engine state lives on
the aiohttp side.
"""
from __future__ import annotations

from aiohttp import web

from .engine import GearheadEngine


def build_app(engine: GearheadEngine) -> web.Application:
    app = web.Application()

    async def health(_req: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "running": engine.running,
            "serial": engine.serial,
        })

    async def state(_req: web.Request) -> web.Response:
        return web.json_response({
            "running": engine.running,
            "serial": engine.serial,
            "cursor": list(engine.cursor()),
            "message": engine.message_line(),
            "cols": engine.cols,
            "rows": engine.rows,
        })

    async def snapshot(_req: web.Request) -> web.Response:
        grid, serial = engine.snapshot()
        # Serialise compactly: each row = list of [char, fg, bg, flags].
        # flags = (bold << 1) | reverse.
        rows = []
        for row in grid:
            rows.append([[c.char, c.fg, c.bg,
                          (1 if c.bold else 0) | (2 if c.reverse else 0)]
                         for c in row])
        return web.json_response({
            "serial": serial,
            "cols": engine.cols,
            "rows": engine.rows,
            "rows_data": rows,
        })

    async def post_key(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        k = body.get("k")
        if k is None:
            return web.json_response({"error": "missing 'k'"}, status=400)
        try:
            engine.post_key(k)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"ok": True})

    app.router.add_get("/health", health)
    app.router.add_get("/state", state)
    app.router.add_get("/snapshot", snapshot)
    app.router.add_post("/key", post_key)
    return app


async def serve(engine: GearheadEngine, *, host: str = "127.0.0.1",
                port: int = 8770) -> tuple[web.AppRunner, web.TCPSite]:
    """Start the REST server. Returns (runner, site); caller cleans up."""
    app = build_app(engine)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    return runner, site
