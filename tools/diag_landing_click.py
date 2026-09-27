#!/usr/bin/env python3
"""Drive a real Chrome over the DevTools protocol and click ENTER SWARMOS.

Answers one question with evidence instead of inference: when the landing page
is served over http, does clicking the CTA actually navigate to the dashboard?

Reports, in order:
  * the URL the browser settled on after load,
  * every console message and page error seen,
  * the CTA note text (the page's own honest status line),
  * the URL after the click,
  * whether the dashboard shell and its canvases exist on the page we landed on.

No pytest, no chromedriver: only the websockets client, which is present.
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
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770/"


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
        # recv(timeout=) is the supported way to poll. Touching ws.socket
        # directly makes the sync client treat the read timeout as fatal and
        # tear the connection down.
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
            out.append("EXCEPTION: %s" % (d.get("text"), ))
    return out


def main() -> int:
    profile = tempfile.mkdtemp(prefix="cdp_landing_")
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
        cdp.drain(4.0)

        settled = cdp.eval("location.href")
        title = cdp.eval("document.title")
        print("after load  url   : %s" % settled)
        print("after load  title : %s" % title)
        print("landing markers   : lp-enter=%s  shell=%s"
              % (cdp.eval("!!document.getElementById('lp-enter')"),
                 cdp.eval("!!document.querySelector('.shell')")))
        print("footer readouts   : fleet=%r  net=%r"
              % (cdp.eval("(document.getElementById('lp-status-fleet-value')||{}).textContent"),
                 cdp.eval("(document.getElementById('lp-status-net-value')||{}).textContent")))
        print("cta note          : %r"
              % cdp.eval("(document.getElementById('lp-cta-note')||{}).textContent"))
        print("cta disabled      : %s"
              % cdp.eval("(document.getElementById('lp-enter')||{}).disabled"))

        for line in console_lines(cdp.events):
            print("  | %s" % line)
        cdp.events.clear()

        print("")
        print("clicking ENTER SWARMOS ...")
        cdp.eval("document.getElementById('lp-enter').click(); 1")
        cdp.drain(5.0)

        after = cdp.eval("location.href")
        print("after click url   : %s" % after)
        print("after click title : %s" % cdp.eval("document.title"))
        print("cta note          : %r"
              % cdp.eval("(document.getElementById('lp-cta-note')||{}).textContent"))
        print("dashboard shell   : %s" % cdp.eval("!!document.querySelector('.shell')"))
        print("map canvases      : %s"
              % cdp.eval("Array.from(document.querySelectorAll('canvas')).map(c=>c.id).join(',')"))
        print("topbar tick       : %r"
              % cdp.eval("(document.getElementById('hdr-tick')||{}).textContent"))
        for line in console_lines(cdp.events):
            print("  | %s" % line)

        cdp.send("Page.captureScreenshot")  # warm
        shot = cdp.send("Page.captureScreenshot", format="png")
        import base64

        with open("/tmp/after_click.png", "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))
        print("screenshot        : /tmp/after_click.png")

        navigated = after.rstrip("/") != settled.rstrip("/")
        print("")
        print("RESULT: navigation %s" % ("HAPPENED" if navigated else "DID NOT HAPPEN"))
        return 0 if navigated else 2
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
