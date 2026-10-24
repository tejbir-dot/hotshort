import asyncio
import os
from playwright.async_api import async_playwright

async def inspect():
    cookie_val = "eyJfZnJlc2giOnRydWUsIl91c2VyX2lkIjoiMSJ9.atyl9Q.V9Qp7lM8KUhAe5efnvHlk9U2EM0"
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome_path, headless=True)
        context = await browser.new_context(
            viewport={'width': 640, 'height': 1386},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True
        )
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
        await page.wait_for_timeout(2000)
        
        info = await page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll('#carousel .clip-card'));
            return cards.map((c, i) => {
                const title = c.querySelector('h3, .card-title, .clip-title, [class*="title"]')?.innerText;
                const badge = c.querySelector('.status-badge, [class*="badge"]')?.innerText;
                const v = c.querySelector('video');
                const vSrc = v ? (v.currentSrc || v.src) : null;
                return {
                    index: i,
                    title: title || c.innerText.split('\\n')[0],
                    badge: badge,
                    hasVideo: !!v,
                    videoSrc: vSrc,
                    width: c.offsetWidth,
                    rect: c.getBoundingClientRect()
                };
            });
        }""")
        print(f"Total cards found in #carousel: {len(info)}")
        for item in info:
            print(f"Card {item['index']}: title={item['title'][:30]!r}, hasVideo={item['hasVideo']}, videoSrc={item['videoSrc']}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
