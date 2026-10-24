import asyncio
from playwright.async_api import async_playwright

async def inspect():
    cookie_val = "eyJfZnJlc2giOnRydWUsIl91c2VyX2lkIjoiMSJ9.atyl9Q.V9Qp7lM8KUhAe5efnvHlk9U2EM0"
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome_path, headless=True)
        context = await browser.new_context(viewport={'width': 640, 'height': 1386})
        await context.add_cookies([{
            'name': 'session',
            'value': cookie_val,
            'domain': '127.0.0.1',
            'path': '/',
            'httpOnly': True,
            'secure': False
        }])
        page = await context.new_page()
        await page.goto("http://127.0.0.1:5000/results/99cdb3e7-169", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        
        html = await page.evaluate("() => document.querySelector('#carousel .clip-card')?.outerHTML || 'none'")
        with open("marketing_factory/clip_card_sample.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Written clip_card_sample.html, len:", len(html))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
