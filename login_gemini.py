import asyncio, os
from playwright.async_api import async_playwright

PROFILE = os.path.expanduser("~/.openclaw/workspace/chrome-profile")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

async def d():
    async with async_playwright() as p:
        b = await p.chromium.launch_persistent_context(
            PROFILE,
            executable_path=CHROME,
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = await b.new_page()
        await page.goto("https://gemini.google.com/app", timeout=60000, wait_until="domcontentloaded")
        input("LOGIN DONE? PRESS ENTER")
        await b.close()

asyncio.run(d())
