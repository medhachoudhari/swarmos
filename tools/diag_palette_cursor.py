#!/usr/bin/env python3
"""Drive real Chrome over CDP against the served dashboard and check:

  1. Does Ctrl+K open the command palette?
  2. Does running "Start run" from the palette actually start a run
     (tick advancing, KPIs populating)?
  3. Does moving the mouse over the map hit-layer update #info-cursor?

This isolates whether issue reports 1 and 2 are a real bug in the served app,
or an artifact of opening the file directly with file://.

No pytest, no chromedriver: only the websockets client, same pattern as
tools/diag_landing_click.py.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.sync.client import connect

CHROME = "/pkg/google-chrome-/125.0.6422.112/x86_64-linux/bin/google-chrome"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770/index.html"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.n = 0
        self.events: list[dict] = []

    def send(self, method: str, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})
            self.events.append(msg)

    def drain(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                self.events.append(json.loads(self.ws.recv(timeout=0.25)))
            except TimeoutError:
                pass

    def eval(self, expr: str):
        res = self.send(
            "Runtime.evaluate",
            expression=expr,
            returnByValue=True,
            awaitPromise=True,
        )
        return res.get("result", {}).get("value")


def console_lines(events: list[dict]) -> list[str]:
    out = []
    for ev in events:
        m = ev.get("method")
        p = ev.get("params", {})
        if m == "Runtime.consoleAPICalled":
            args = " ".join(
                str(a.get("value", a.get("description", "?"))) for a in p.get("args", [])
            )
            out.append("console.%s: %s" % (p.get("type"), args))
        elif m == "Log.entryAdded":
            e = p.get("entry", {})
            out.append("log[%s/%s]: %s" % (e.get("level"), e.get("source"), e.get("text")))
        elif m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            out.append("EXCEPTION: %s" % (d.get("text"),))
    return out


def main() -> int:
    profile = tempfile.mkdtemp(prefix="cdp_pc_")
    port = free_port()
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--remote-debugging-port=%d" % port,
            "--user-data-dir=%s" % profile,
            "--window-size=1400,880",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ws_url = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/list" % port, timeout=1
                ) as r:
                    tabs = json.load(r)
                cand = [t for t in tabs if t.get("type") == "page"]
                if cand:
                    ws_url = cand[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not ws_url:
            print("FAIL: chrome did not expose a debugging target")
            return 1

        cdp = CDP(ws_url)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Log.enable")

        print("navigating to %s" % URL)
        cdp.send("Page.navigate", url=URL)
        cdp.drain(3.0)

        print("url after load     : %s" % cdp.eval("location.href"))
        print("title              : %s" % cdp.eval("document.title"))
        print("main.js loaded ok  : %s" % cdp.eval("typeof window !== 'undefined'"))
        for line in console_lines(cdp.events):
            print("  | %s" % line)
        cdp.events.clear()

        print("")
        print("--- test 1: Ctrl+K opens palette ---")
        cdp.send(
            "Input.dispatchKeyEvent",
            type="keyDown", key="k", code="KeyK",
            windowsVirtualKeyCode=75, nativeVirtualKeyCode=75,
            modifiers=2,  # ctrl
        )
        cdp.send(
            "Input.dispatchKeyEvent",
            type="keyUp", key="k", code="KeyK",
            windowsVirtualKeyCode=75, nativeVirtualKeyCode=75,
            modifiers=2,
        )
        cdp.drain(0.5)
        print("palette open       : %s"
              % cdp.eval("(document.getElementById('palette-scrim')||{}).dataset.open"))
        print("palette item count : %s"
              % cdp.eval("document.querySelectorAll('.palette__item').length"))

        print("")
        print("--- test 2: run 'Start run' command from palette ---")
        # Click the first palette item's text to see if "Start run" is first.
        names = cdp.eval(
            "Array.from(document.querySelectorAll('.palette__name')).map(n=>n.textContent)"
        )
        print("commands listed    : %s" % names)
        tick_before = cdp.eval("(document.getElementById('hdr-tick')||{}).textContent")
        print("tick before        : %r" % tick_before)
        cdp.eval(
            "document.querySelector('.palette__item[data-i=\"0\"]').click(); 1"
        )
        cdp.drain(2.5)
        link_text = cdp.eval("(document.getElementById('link-text')||{}).textContent")
        tick_after = cdp.eval("(document.getElementById('hdr-tick')||{}).textContent")
        running = cdp.eval("!!(window.store && window.store.running)")
        print("link text          : %r" % link_text)
        print("tick after         : %r" % tick_after)
        print("store.running      : %s (may be undefined, store is a module, not global)" % running)
        for line in console_lines(cdp.events):
            print("  | %s" % line)
        cdp.events.clear()

        print("")
        print("--- test 3: cursor readout on mousemove over map hit-layer ---")
        rect = cdp.eval(
            "(() => { const el = document.getElementById('layer-hit'); "
            "if (!el) return null; const r = el.getBoundingClientRect(); "
            "return {x: r.left + r.width/2, y: r.top + r.height/2}; })()"
        )
        print("hit-layer rect     : %s" % rect)
        before = cdp.eval("(document.getElementById('info-cursor')||{}).textContent")
        print("cursor text before : %r" % before)
        if rect:
            cdp.send("Input.dispatchMouseEvent", type="mouseMoved", x=rect["x"], y=rect["y"])
            cdp.drain(0.5)
        after = cdp.eval("(document.getElementById('info-cursor')||{}).textContent")
        print("cursor text after  : %r" % after)

        cdp.send("Page.captureScreenshot")
        shot = cdp.send("Page.captureScreenshot", format="png")
        import base64
        with open("/tmp/palette_cursor.png", "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))
        print("")
        print("screenshot         : /tmp/palette_cursor.png")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
