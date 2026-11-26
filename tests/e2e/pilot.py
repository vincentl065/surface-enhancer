"""Drive a headless Chrome through the DevTools protocol: mouse, keyboard, file inputs, screenshots.

Own profile folder and own debugging port, so that it never touches the browser you are using. Needs ``aiohttp``
(test-only dependency) and a Chrome / Chromium / Edge binary (set ``CHROME`` to its path if it is not found).
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CANDIDATES = [os.environ.get("CHROME"), "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
              "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("chrome")]


def find_chrome():
    for c in CANDIDATES:
        if c and Path(c).exists():
            return str(c)
    return None


def port_is_free(port: int) -> bool:
    """Free on EVERY address (a check on 127.0.0.1 alone is not enough on Windows)."""
    import socket
    try:
        import psutil
        if any(c.laddr and c.laddr.port == port and c.status == "LISTEN" for c in psutil.net_connections("tcp")):
            return False
    except Exception:
        pass
    for host in ("0.0.0.0", "127.0.0.1"):
        s = socket.socket()
        try:
            if sys.platform == "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((host, port))
        except OSError:
            return False
        finally:
            s.close()
    return True


def free_port(first: int, last: int) -> int:
    for p in range(first, last + 1):
        if port_is_free(p):
            return p
    raise RuntimeError(f"no free port between {first} and {last}")


class Pilot:
    def __init__(self, width=1366, height=768, debug_port=None):
        self.w, self.h = width, height
        self.errors = []
        self.n = 0
        self.port = debug_port or free_port(9361, 9379)

    async def __aenter__(self):
        import aiohttp
        chrome = find_chrome()
        if not chrome:
            raise RuntimeError("no Chrome / Chromium found: set the CHROME environment variable to its path")
        self.profile = Path(tempfile.mkdtemp(prefix="surface_enhancer_chrome_"))
        self.pr = subprocess.Popen([chrome, "--headless=new", f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                    "--hide-scrollbars", "--no-first-run", "--disable-extensions", f"--window-size={self.w},{self.h}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.s = aiohttp.ClientSession()
        target = None
        for _ in range(120):
            try:
                async with self.s.get(f"http://127.0.0.1:{self.port}/json") as r:
                    target = next(t for t in await r.json() if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.25)
        if target is None:
            raise RuntimeError("headless Chrome did not start")
        self.ws = await self.s.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0)
        await self.cmd("Emulation.setDeviceMetricsOverride", width=self.w, height=self.h, deviceScaleFactor=1, mobile=False)
        for d in ("Runtime", "Page", "Log", "DOM"):
            await self.cmd(d + ".enable")
        return self

    async def __aexit__(self, *a):
        try:
            await self.ws.close()
            await self.s.close()
        finally:
            self.pr.terminate()
            try:
                self.pr.wait(8)
            except Exception:
                self.pr.kill()
            shutil.rmtree(self.profile, ignore_errors=True)

    def _event(self, m):
        k = m.get("method")
        if k == "Runtime.exceptionThrown":
            d = m["params"]["exceptionDetails"]
            self.errors.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", ""))[:300])
        elif k == "Runtime.consoleAPICalled" and m["params"]["type"] in ("error", "assert"):
            self.errors.append("console: " + " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"])[:300])
        elif k == "Log.entryAdded" and m["params"]["entry"]["level"] == "error":
            e = m["params"]["entry"]
            self.errors.append(f"log: {e.get('text', '')[:200]} {e.get('url', '')}")

    async def cmd(self, method, **params):
        self.n += 1
        me = self.n
        await self.ws.send_json(dict(id=me, method=method, params=params))
        while True:
            m = json.loads((await self.ws.receive()).data)
            if m.get("id") == me:
                return m.get("result", m.get("error"))
            self._event(m)

    async def goto(self, url):
        await self.cmd("Page.navigate", url=url)

    async def resize(self, width, height):
        self.w, self.h = width, height
        await self.cmd("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"].get("exception", {}).get("description", ""))[:400])
        return r.get("result", {}).get("value")

    async def wait(self, expr, timeout=30.0, step=0.15):
        for _ in range(int(timeout / step)):
            if await self.js(expr):
                return True
            await asyncio.sleep(step)
        raise TimeoutError("timed out waiting for: " + expr)

    async def set_files(self, selector, paths):
        doc = await self.cmd("DOM.getDocument")
        node = await self.cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)
        await self.cmd("DOM.setFileInputFiles", nodeId=node["nodeId"], files=[str(p) for p in paths])

    async def allow_downloads(self, folder):
        await self.cmd("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(folder))

    async def mouse(self, type_, x, y, button="none", buttons=0, clicks=0, shift=False):
        await self.cmd("Input.dispatchMouseEvent", type=type_, x=x, y=y, button=button, buttons=buttons, clickCount=clicks, modifiers=8 if shift else 0)

    async def hover(self, x, y):
        await self.mouse("mouseMoved", x - 3, y - 2)
        await asyncio.sleep(0.03)
        await self.mouse("mouseMoved", x, y)

    async def click(self, x, y, button="left"):
        await self.mouse("mouseMoved", x, y)
        await self.mouse("mousePressed", x, y, button, 1 if button == "left" else 2, 1)
        await self.mouse("mouseReleased", x, y, button, 0, 1)

    async def click_on(self, selector):
        r = await self.js(f"(()=>{{const e=document.querySelector({json.dumps(selector)}); if(!e) return null; e.scrollIntoView({{block:'center'}}); const r=e.getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]}})()")
        if not r:
            raise RuntimeError("no element for " + selector)
        await self.click(r[0], r[1])

    async def press(self, x, y, shift=False):
        await self.mouse("mouseMoved", x, y)
        await self.mouse("mousePressed", x, y, "left", 1, 1, shift)

    async def drag_to(self, x0, y0, x1, y1, n=8, shift=False):
        for i in range(1, n + 1):
            await self.mouse("mouseMoved", x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, "left", 1, 0, shift)
            await asyncio.sleep(0.02)

    async def release(self, x, y, shift=False):
        await self.mouse("mouseReleased", x, y, "left", 0, 1, shift)

    async def drag(self, x0, y0, x1, y1, shift=False):
        await self.press(x0, y0, shift)
        await self.drag_to(x0, y0, x1, y1, shift=shift)
        await self.release(x1, y1, shift)

    async def wheel(self, x, y, dy):
        await self.cmd("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=dy)

    async def key(self, key, code=None, ctrl=False, vk=0, text=None):
        await self.cmd("Input.dispatchKeyEvent", type="keyDown" if text else "rawKeyDown", key=key, code=code or key, windowsVirtualKeyCode=vk, modifiers=2 if ctrl else 0, **({"text": text} if text else {}))
        await self.cmd("Input.dispatchKeyEvent", type="keyUp", key=key, code=code or key, windowsVirtualKeyCode=vk, modifiers=2 if ctrl else 0)

    async def type(self, selector, text):
        await self.js(f"(()=>{{const e=document.querySelector({json.dumps(selector)}); e.focus(); e.value={json.dumps(text)}; e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")

    async def screenshot(self, path):
        r = await self.cmd("Page.captureScreenshot", format="png")
        Path(path).write_bytes(base64.b64decode(r["data"]))
        return path
