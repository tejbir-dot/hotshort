import asyncio
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
        await page.wait_for_timeout(1500)
        
        cards = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('#carousel .clip-card')).map((c, i) => {
                const vid = c.querySelector('video');
                const title = c.querySelector('h3, .card-title, .clip-title, [class*="title"]')?.textContent?.trim();
                const quote = c.querySelector('.quote-text, .transcript-snippet, [class*="quote"], p')?.textContent?.trim();
                const score = c.querySelector('[class*="viral"], [class*="score"]')?.textContent?.trim();
                return {
                    i,
                    title: title || 'No Title',
                    score: score || '',
                    quote: quote ? quote.substring(0, 60) : '',
                    hasVideo: !!vid,
                    videoSrc: vid ? (vid.currentSrc || vid.src) : ''
                };
            });
        }""")
        
        with open("marketing_factory/cards_dump.txt", "w", encoding="utf-8") as f:
            f.write(f"Total cards: {len(cards)}\n")
            for c in cards:
                f.write(f"Card {c['i']}: score={c['score']}, title={c['title']}\n")
                f.write(f"   quote={c['quote']}\n")
                f.write(f"   video={c['videoSrc']}\n")
                
        print("Saved cards_dump.txt with", len(cards), "cards.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
