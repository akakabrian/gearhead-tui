"""Agent REST API QA.

Starts the API on a free ephemeral port, exercises each endpoint, and
asserts shape + semantics. Engine runs headlessly — no Textual.

Run: .venv/bin/python -m tests.api_qa
"""
from __future__ import annotations

import asyncio
import socket
import sys
import time

import aiohttp

from gearhead_tui import agent_api
from gearhead_tui.engine import GearheadEngine


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_engine(e: GearheadEngine, marker: str = "GearHead",
                           timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        g, _ = e.snapshot()
        if any(marker in "".join(c.char for c in row) for row in g):
            return True
        await asyncio.sleep(0.1)
    return False


async def main_async() -> int:
    port = _free_port()
    engine = GearheadEngine(cols=100, rows=40)
    engine.start()
    runner, _site = await agent_api.serve(engine, port=port)

    results: list[tuple[str, bool, str]] = []

    def report(name: str, ok: bool, msg: str = "") -> None:
        results.append((name, ok, msg))
        print(f"  {name:40s} {'PASS' if ok else 'FAIL — ' + msg}")

    try:
        base = f"http://127.0.0.1:{port}"
        await _wait_for_engine(engine)

        async with aiohttp.ClientSession() as sess:
            # /health
            async with sess.get(f"{base}/health") as r:
                body = await r.json()
                try:
                    assert r.status == 200
                    assert body["ok"] is True
                    assert "running" in body and "serial" in body
                    report("health", True)
                except AssertionError as e:
                    report("health", False, f"{e} body={body}")

            # /state
            async with sess.get(f"{base}/state") as r:
                body = await r.json()
                try:
                    assert r.status == 200
                    for k in ("running", "serial", "cursor", "message",
                              "cols", "rows"):
                        assert k in body, f"missing key {k}"
                    assert body["cols"] == 100 and body["rows"] == 40
                    assert isinstance(body["cursor"], list) and len(body["cursor"]) == 2
                    report("state", True)
                except AssertionError as e:
                    report("state", False, f"{e} body={body}")

            # /snapshot — cost + shape
            t0 = time.perf_counter()
            async with sess.get(f"{base}/snapshot") as r:
                body = await r.json()
            t1 = time.perf_counter()
            try:
                assert r.status == 200
                assert body["cols"] == 100
                assert body["rows"] == 40
                assert len(body["rows_data"]) == 40
                assert len(body["rows_data"][0]) == 100
                # Each cell: [char, fg, bg, flags]
                c0 = body["rows_data"][0][0]
                assert isinstance(c0, list) and len(c0) == 4
                assert (t1 - t0) < 1.0, f"snapshot slow: {t1-t0:.3f}s"
                report("snapshot", True)
            except AssertionError as e:
                report("snapshot", False, f"{e}")

            # /key — named key + raw char, both should advance serial
            before = engine.serial
            async with sess.post(f"{base}/key", json={"k": "down"}) as r:
                body = await r.json()
                assert r.status == 200 and body["ok"] is True
            await asyncio.sleep(0.3)
            try:
                assert engine.serial > before, (
                    f"serial {before}→{engine.serial} after /key down"
                )
                report("key (down)", True)
            except AssertionError as e:
                report("key (down)", False, str(e))

            before = engine.serial
            async with sess.post(f"{base}/key", json={"k": "2"}) as r:
                assert r.status == 200
            await asyncio.sleep(0.3)
            try:
                assert engine.serial > before, (
                    f"serial {before}→{engine.serial} after /key '2'"
                )
                report("key ('2')", True)
            except AssertionError as e:
                report("key ('2')", False, str(e))

            # /key — malformed request
            async with sess.post(f"{base}/key", data=b"not json") as r:
                try:
                    assert r.status == 400
                    report("key malformed rejected", True)
                except AssertionError as e:
                    report("key malformed rejected", False,
                           f"expected 400, got {r.status}")

            async with sess.post(f"{base}/key", json={"oops": 1}) as r:
                try:
                    assert r.status == 400
                    report("key missing 'k' rejected", True)
                except AssertionError as e:
                    report("key missing 'k' rejected", False,
                           f"expected 400, got {r.status}")
    finally:
        await runner.cleanup()
        engine.stop(timeout=1.5)

    passes = sum(1 for _, ok, _ in results if ok)
    print()
    print(f"  {passes}/{len(results)} API scenarios passed")
    return 0 if passes == len(results) else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
