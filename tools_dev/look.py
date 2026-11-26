"""Developer helper: screenshots of the home page and of the editor of a running server (headless Chrome).

    python tools_dev/look.py http://127.0.0.1:8811 <segment> <output folder> [width height]
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "e2e"))
from pilot import Pilot  # noqa: E402


async def main():
    base, seg, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    w, h = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (1366, 768)
    out.mkdir(parents=True, exist_ok=True)
    async with Pilot(w, h) as p:
        await p.goto(base + "/")
        await p.wait("window.READY === true", 20)
        await asyncio.sleep(0.5)
        await p.screenshot(out / "home.png")
        await p.js("window.scrollTo(0, 500)")
        await asyncio.sleep(0.2)
        await p.screenshot(out / "home_2.png")
        await p.goto(f"{base}/editor.html?s={seg}&neuf")
        await p.wait("window.PRET === true", 40)
        await asyncio.sleep(1.0)
        r = await p.js("(()=>{const c=document.getElementById('page').getBoundingClientRect();return [c.left,c.top,c.width,c.height]})()")
        await p.click(r[0] + r[2] / 2, r[1] + r[3] / 2)
        await asyncio.sleep(1.0)
        await p.screenshot(out / "editor.png")
        await p.key("?", text="?")
        await asyncio.sleep(0.3)
        await p.screenshot(out / "editor_help.png")
        await p.key("Escape", vk=27)
        await p.click_on("#exporter")
        await asyncio.sleep(0.3)
        await p.screenshot(out / "editor_export.png")
        await p.key("Escape", vk=27)
        await p.key("Tab", vk=9)
        await asyncio.sleep(2.0)
        await p.screenshot(out / "editor_3d.png")
        print("errors:", p.errors)


asyncio.run(main())
