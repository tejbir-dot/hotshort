import asyncio
import os
import subprocess
from playwright.async_api import async_playwright

async def verify_34_clips_recording():
    base_dir = r"c:\Users\n\Documents\hotshort\marketing_factory"
    raw_dir = os.path.join(base_dir, "test_34_raw")
    os.makedirs(raw_dir, exist_ok=True)
    
    for f in os.listdir(raw_dir):
        if f.endswith(".webm"):
            try: os.remove(os.path.join(raw_dir, f))
            except: pass
            
    cookie_val = "eyJfZnJlc2giOnRydWUsIl91c2VyX2lkIjoiMSJ9.atyl9Q.V9Qp7lM8KUhAe5efnvHlk9U2EM0"
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    w, h = 640, 1386
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=chrome_path,
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--enable-features=TouchEvents',
                '--autoplay-policy=no-user-gesture-required'
            ]
        )
        context = await browser.new_context(
            viewport={'width': w, 'height': h},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            color_scheme='dark',
            record_video_dir=raw_dir,
            record_video_size={'width': w, 'height': h}
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
        print("Navigating to http://127.0.0.1:5000/results/99cdb3e7-169...", flush=True)
        await page.goto("http://127.0.0.1:5000/results/99cdb3e7-169", wait_until="networkidle")
        
        # Explicitly wait for .clip-card to be in the DOM!
        print("Waiting for .clip-card selector to appear...", flush=True)
        await page.wait_for_selector("#carousel .clip-card", timeout=15000)
        await page.wait_for_timeout(800)
        
        # Inject the 34 cards with the 7 clips
        print("Injecting 34 cards with 7 user clips...", flush=True)
        await page.evaluate("""() => {
            const carousel = document.getElementById('carousel');
            if (!carousel) return;
            
            const existingCards = Array.from(carousel.querySelectorAll('.clip-card'));
            if (existingCards.length === 0) return;
            
            const userClips = [
                '/static/clip_files/99cdb3e7_branded_0_246_328.mp4',
                '/static/clip_files/99cdb3e7_branded_3_102_189.mp4',
                '/static/clip_files/99cdb3e7_edited_2_246_328.mp4',
                '/static/clip_files/a3f63caa_branded_1_388_467.mp4',
                '/static/clip_files/b1d60a78_branded_0_50_118.mp4',
                '/static/clip_files/b1d60a78_branded_1_1_68.mp4',
                '/static/clip_files/b1d60a78_branded_2_32_99.mp4'
            ];
            
            const viralMeta = [
                { tag: '🏆 Best Pick', score: '98% Viral', hook: 'When Champion Pushes The Pain', ending: 'Clean Ending', pot: '98%' },
                { tag: '🔥 Most Viral', score: '97% Viral', hook: 'Speed Tries WWE Moves For Real', ending: 'Dopamine Peak', pot: '97%' },
                { tag: '⚡ High Energy', score: '96% Viral', hook: 'Randy Orton WWE Ring Test', ending: 'Curiosity Gap', pot: '96%' },
                { tag: '🎯 Hook King', score: '95% Viral', hook: 'Trading Psychology Brutal Truth', ending: 'Mindset Shift', pot: '95%' },
                { tag: '🧠 Mindset Peak', score: '95% Viral', hook: 'How Top 1% Think Under Pressure', ending: 'Dopamine Loop', pot: '95%' },
                { tag: '💥 Shock Drop', score: '94% Viral', hook: 'The Moment Everything Changed', ending: 'Clean Ending', pot: '94%' },
                { tag: '🚀 Viral Gold', score: '93% Viral', hook: 'Uncut Raw Podcast Confession', ending: 'Curiosity Loop', pot: '93%' }
            ];
            
            // Update live studio pill
            const pill = document.querySelector('.live-studio-pill');
            if (pill) {
                pill.className = 'live-studio-pill is-completed';
                pill.innerHTML = '⚡ 34 of 34 Viral Shorts Ready &amp; Playing (100% Complete)';
            }
            
            // Update labels
            const labelSpan = document.querySelector('.carousel-label span');
            if (labelSpan) {
                labelSpan.innerHTML = 'YOUR TOP CLIPS <span style=\"background: linear-gradient(90deg, #ffc864, #ff9000); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 0.88em; font-weight: 800; margin-left: 8px;\">(34 Ready Shorts)</span>';
            }
            
            const batchBtn = document.getElementById('batchExportBtn');
            if (batchBtn) {
                batchBtn.innerHTML = '<span>⚡ Batch Export All 34 (TikTok)</span>';
            }
            
            const tplCard = existingCards[0].cloneNode(true);
            carousel.innerHTML = '';
            
            for (let i = 0; i < 34; i++) {
                const card = tplCard.cloneNode(true);
                card.classList.remove('is-best');
                if (i === 0) card.classList.add('is-best');
                
                const meta = viralMeta[i % viralMeta.length];
                const clipNum = i + 1;
                const vidSrc = userClips[i % userClips.length];
                
                // Badges
                const badgeGroup = card.querySelector('.badge-group');
                if (badgeGroup) {
                    badgeGroup.innerHTML = `
                        <div class=\"status-chip chip-ready\"><span class=\"chip-dot\"></span> Ready</div>
                        <div class=\"badge best\" style=\"background: rgba(255,180,0,0.18); border-color: rgba(255,200,0,0.4); color: #ffd070;\">${meta.tag}</div>
                        <span class=\"clip-duration-badge\">⏱️ 1:${(15 + (i * 7) % 45).toString().padStart(2, '0')}</span>
                        <span class=\"viral-score-pill\" style=\"background: rgba(255,120,0,0.18); border-color: rgba(255,140,0,0.4); color: #ff9838;\">🔥 ${meta.score}</span>
                    `;
                }
                
                // Hook text
                const hookText = card.querySelector('.hook-text');
                if (hookText) hookText.innerText = `\"Viral Clip #${clipNum}\"`;
                
                const cardHook = card.querySelector('.card-hook-line');
                if (cardHook) cardHook.innerText = `\"Viral Clip #${clipNum}\"`;
                
                const quoteText = card.querySelector('.transcript-snippet-text');
                if (quoteText) quoteText.innerText = `${meta.hook}... This is why this clip has a 98% retention curve with high dopamine pacing.`;
                
                const endingLabel = card.querySelector('.hook-label');
                if (endingLabel) endingLabel.innerText = meta.ending;
                
                const potVal = card.querySelector('.confidence-value');
                if (potVal) potVal.innerText = `${meta.pot} Potential`;
                
                const potBar = card.querySelector('.confidence-fill');
                if (potBar) potBar.style.width = meta.pot;
                
                // Video inside masked clip preview
                const vid = card.querySelector('video');
                if (vid) {
                    vid.src = vidSrc;
                    vid.muted = true;
                    vid.loop = true;
                    vid.playsInline = true;
                    vid.autoplay = true;
                    vid.play().catch(() => {});
                }
                
                carousel.appendChild(card);
            }
        }""")
        
        # Scroll carousel into view
        await page.evaluate("""() => {
            const c = document.getElementById('carousel');
            if (c) c.scrollIntoView({ behavior: 'auto', block: 'center' });
        }""")
        await page.wait_for_timeout(1000)
        
        # Continuous smooth glide
        print("Gliding forward through cards...", flush=True)
        await page.evaluate("""() => {
            return new Promise((resolve) => {
                const carousel = document.getElementById('carousel');
                if (!carousel) return resolve();
                
                let current = 0;
                const target = 2800; // slides across ~7-8 cards
                const speed = 5.5;   // pixels per tick (~330px/sec)
                
                const timer = setInterval(() => {
                    current += speed;
                    carousel.scrollLeft = current;
                    
                    // Keep visible videos playing
                    const vids = carousel.querySelectorAll('video');
                    vids.forEach(v => {
                        const rect = v.getBoundingClientRect();
                        if (rect.right > -100 && rect.left < window.innerWidth + 100) {
                            if (v.paused) v.play().catch(() => {});
                        }
                    });
                    
                    if (current >= target) {
                        clearInterval(timer);
                        resolve();
                    }
                }, 16);
            });
        }""")
        
        await page.wait_for_timeout(1200)
        print("Glide complete! Closing...", flush=True)
        await context.close()
        await browser.close()
        
    webms = [f for f in os.listdir(raw_dir) if f.endswith(".webm")]
    if webms:
        webms.sort(key=lambda f: os.path.getmtime(os.path.join(raw_dir, f)), reverse=True)
        raw_webm = os.path.join(raw_dir, webms[0])
        mp4_out = os.path.join(base_dir, "test_carousel", "verify_34_glide.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_webm,
            "-r", "60", "-c:v", "libx264", "-crf", "16", "-preset", "fast",
            mp4_out
        ], check=True)
        print("Saved verify MP4:", mp4_out)
        
        for t, name in [(1.5, "v34_f1.jpg"), (3.5, "v34_f2.jpg"), (5.5, "v34_f3.jpg"), (7.5, "v34_f4.jpg"), (9.0, "v34_f5.jpg")]:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(t), "-i", mp4_out, "-frames:v", "1",
                os.path.join(base_dir, "test_carousel", name)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Snapshots written successfully!")

if __name__ == "__main__":
    asyncio.run(verify_34_clips_recording())
