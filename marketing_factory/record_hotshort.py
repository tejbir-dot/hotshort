import asyncio
import os
import subprocess
import time
from playwright.async_api import async_playwright

async def record_masterpiece_full():
    base_dir = r"c:\Users\n\Documents\hotshort\marketing_factory"
    raw_dir_1 = os.path.join(base_dir, "raw_hotshort_part1")
    raw_dir_2 = os.path.join(base_dir, "raw_hotshort_part2")
    os.makedirs(raw_dir_1, exist_ok=True)
    os.makedirs(raw_dir_2, exist_ok=True)
    
    final_output = os.path.join(base_dir, "remotion_engine", "public", "hotshort_demo.mp4")
    part1_trimmed = os.path.join(base_dir, "part1_trimmed.mp4")
    part2_trimmed = os.path.join(base_dir, "part2_trimmed.mp4")
    
    for d in [raw_dir_1, raw_dir_2]:
        for f in os.listdir(d):
            if f.endswith(".webm"):
                try: os.remove(os.path.join(d, f))
                except: pass

    cookie_val = "eyJfZnJlc2giOnRydWUsIl91c2VyX2lkIjoiMSJ9.atyl9Q.V9Qp7lM8KUhAe5efnvHlk9U2EM0"
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = None
        
    w, h = 640, 1386
    rec_w, rec_h = 1920, 4158
    
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
        
        # ═══════════════════════════════════════════════════════════════
        # PART 1: HOME PAGE (0.0s - 6.0s, exactly 6.00s)
        # 0s - 3s: Link typing in URL input
        # 3s - 4s: Analyze Now button tap -> Vibe Modal opens
        # 4s - 6s: Vibe select (Center Crop TikTok) & modal button tap
        # ═══════════════════════════════════════════════════════════════
        print("--- RECORDING PART 1: HOME PAGE FLOW ---", flush=True)
        t_start_c1 = time.time()
        context1 = await browser.new_context(
            viewport={'width': w, 'height': h},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            color_scheme='dark',
            record_video_dir=raw_dir_1,
            record_video_size={'width': w, 'height': h}
        )
        
        page1 = await context1.new_page()
        await page1.goto("http://127.0.0.1:5000", wait_until="networkidle", timeout=30000)
        input_el = await page1.wait_for_selector("input[name='youtube_url'], .form-input", timeout=5000)
        await page1.evaluate("() => window.scrollTo(0, 0)")
        await page1.wait_for_timeout(300)
        
        t_home_ready = time.time()
        trim_offset_1 = t_home_ready - t_start_c1
        print(f"Homepage ready at offset {trim_offset_1:.3f}s", flush=True)
        
        # 0.0s - 3.0s: Type URL
        if input_el:
            await input_el.click()
            await page1.wait_for_timeout(100)
            yt_url = "https://youtube.com/watch?v=speed_stream"
            await page1.keyboard.type(yt_url, delay=52)
            
        elapsed = time.time() - t_home_ready
        if elapsed < 3.0:
            await page1.wait_for_timeout(int((3.0 - elapsed) * 1000))
            
        # 3.0s - 4.0s: Tap Analyze Now -> Opens Vibe Modal!
        print("Part 1: Tapping Analyze Now at 3.0s...", flush=True)
        analyze_btn = await page1.wait_for_selector("#homeAnalyzeBtn, button.btn-primary", timeout=5000)
        if analyze_btn:
            await analyze_btn.click()
            
        elapsed = time.time() - t_home_ready
        if elapsed < 4.2:
            await page1.wait_for_timeout(int((4.2 - elapsed) * 1000))
            
        # 4.2s - 6.0s: Vibe select modal (Select Center Crop card)
        print("Part 1: Selecting Center Crop vibe...", flush=True)
        await page1.wait_for_selector(".vibe-card.tjr", timeout=5000)
        await page1.evaluate("""() => {
            const card = document.querySelector(".vibe-card.tjr");
            if (card) selectVibe(card);
        }""")
        await page1.wait_for_timeout(900)
        
        # Visual tap effect on modal Analyze button (no page redirect)
        await page1.evaluate("""() => {
            const btn = document.getElementById("vibeGoBtn");
            if (btn) {
                btn.disabled = false;
                btn.style.transform = "scale(0.96)";
                btn.style.boxShadow = "0 0 35px rgba(255, 180, 50, 0.9)";
            }
        }""")
        
        elapsed = time.time() - t_home_ready
        if elapsed < 6.0:
            await page1.wait_for_timeout(int((6.0 - elapsed) * 1000))
            
        await context1.close()
        print("Part 1 recorded cleanly!", flush=True)

        # ═══════════════════════════════════════════════════════════════
        # PART 2: RESULTS PAGE & 4 JUMP CUTS (6.0s - 12.8s, exactly 6.80s)
        # Starts with Card #1 fully centered
        # Jump cut every 1.2s to Card #2, Card #3, Card #4
        # ═══════════════════════════════════════════════════════════════
        print("--- PREPARING PART 2: RESULTS PAGE & 4 CLIPS ---", flush=True)
        t_start_c2 = time.time()
        context2 = await browser.new_context(
            viewport={'width': w, 'height': h},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            color_scheme='dark',
            record_video_dir=raw_dir_2,
            record_video_size={'width': w, 'height': h}
        )
        page2 = await context2.new_page()
        
        # Add auth cookie for results page
        await context2.add_cookies([{
            'name': 'session',
            'value': cookie_val,
            'domain': '127.0.0.1',
            'path': '/',
            'httpOnly': True,
            'secure': False
        }])
        
        await page2.goto("http://127.0.0.1:5000/results/99cdb3e7-169", wait_until="networkidle")
        await page2.wait_for_selector("#carousel .clip-card", timeout=15000)
        
        # Inject 4 clean clips with object-fit: cover and seamless background blur
        print("Injecting 4 clean clips into carousel...", flush=True)
        await page2.evaluate("""async () => {
            const carousel = document.getElementById('carousel');
            if (!carousel) return;
            
            const existingCards = Array.from(carousel.querySelectorAll('.clip-card'));
            if (existingCards.length === 0) return;
            
            const cleanClips = [
                { vid: '/static/clean_clips/b1d60a78_branded_0_50_118.mp4', poster: '/static/clean_clips/poster_0.jpg' },
                { vid: '/static/clean_clips/a3f63caa_branded_1_388_467.mp4', poster: '/static/clean_clips/poster_1.jpg' },
                { vid: '/static/clean_clips/b1d60a78_branded_1_1_68.mp4', poster: '/static/clean_clips/poster_2.jpg' },
                { vid: '/static/clean_clips/99cdb3e7_branded_3_102_189.mp4', poster: '/static/clean_clips/poster_3.jpg' }
            ];
            
            const viralMeta = [
                { tag: '🏆 Best Pick', score: '99% Viral', hook: 'Speed In India Meets Craziest Fans', ending: 'Clean Ending', pot: '99%' },
                { tag: '🔥 Most Viral', score: '98% Viral', hook: 'How I Built A 7-Figure Business', ending: 'Dopamine Peak', pot: '98%' },
                { tag: '⚡ High Energy', score: '97% Viral', hook: 'Trading Psychology & Risk Secret', ending: 'Curiosity Gap', pot: '97%' },
                { tag: '🧠 Mindset Peak', score: '95% Viral', hook: 'The Brutal Truth About 9-to-5', ending: 'Dopamine Loop', pot: '95%' }
            ];
            
            const style = document.createElement('style');
            style.innerHTML = `
                .clip-preview {
                    background: transparent !important;
                    aspect-ratio: 9 / 16 !important;
                    overflow: hidden !important;
                }
                .clip-preview video {
                    width: 100% !important;
                    height: 100% !important;
                    object-fit: cover !important;
                    filter: none !important;
                    display: block !important;
                }
                .hook-glass-overlay {
                    display: none !important;
                }
            `;
            document.head.appendChild(style);
            
            const pill = document.querySelector('.live-studio-pill');
            if (pill) {
                pill.className = 'live-studio-pill is-completed';
                pill.innerHTML = '⚡ 34 of 34 Viral Shorts Ready &amp; Playing (100% Complete)';
            }
            
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
            
            for (let i = 0; i < 4; i++) {
                const card = tplCard.cloneNode(true);
                card.classList.remove('is-best');
                card.classList.remove('is-previewing');
                if (i === 0) {
                    card.classList.add('is-best');
                    card.classList.add('is-previewing');
                }
                
                const meta = viralMeta[i];
                const clipNum = i + 1;
                const clipData = cleanClips[i];
                
                const badgeGroup = card.querySelector('.badge-group');
                if (badgeGroup) {
                    badgeGroup.innerHTML = `
                        <div class=\"status-chip chip-ready\"><span class=\"chip-dot\"></span> Ready</div>
                        <div class=\"badge best\" style=\"background: rgba(255,180,0,0.18); border-color: rgba(255,200,0,0.4); color: #ffd070;\">${meta.tag}</div>
                        <span class=\"clip-duration-badge\">⏱️ 1:${(15 + i * 14).toString().padStart(2, '0')}</span>
                        <span class=\"viral-score-pill\" style=\"background: rgba(255,120,0,0.18); border-color: rgba(255,140,0,0.4); color: #ff9838;\">🔥 ${meta.score}</span>
                    `;
                }
                
                const hookText = card.querySelector('.hook-text');
                if (hookText) hookText.innerText = `\"Viral Clip #${clipNum}\"`;
                
                const cardHook = card.querySelector('.card-hook-line');
                if (cardHook) cardHook.innerText = `\"Viral Clip #${clipNum}\"`;
                
                const quoteText = card.querySelector('.transcript-snippet-text');
                if (quoteText) quoteText.innerText = `${meta.hook}... High retention pacing & auto-synced subtitles.`;
                
                const endingLabel = card.querySelector('.hook-label');
                if (endingLabel) endingLabel.innerText = meta.ending;
                
                const potVal = card.querySelector('.confidence-value');
                if (potVal) potVal.innerText = `${meta.pot} Potential`;
                
                const potBar = card.querySelector('.confidence-fill');
                if (potBar) potBar.style.width = meta.pot;
                
                const vid = card.querySelector('video');
                if (vid) {
                    vid.src = clipData.vid;
                    vid.poster = clipData.poster;
                    vid.preload = 'auto';
                    vid.muted = true;
                    vid.loop = true;
                    vid.playsInline = true;
                    vid.autoplay = true;
                    vid.currentTime = 0.5;
                    vid.style.filter = 'none';
                    vid.style.objectFit = 'cover';
                    vid.style.width = '100%';
                    vid.style.height = '100%';
                    vid.play().catch(() => {});
                }
                
                carousel.appendChild(card);
            }
        }""")
        
        # Center carousel and disable snap for instantaneous jump cuts
        await page2.evaluate("""() => {
            const c = document.getElementById('carousel');
            if (c) {
                c.scrollIntoView({ behavior: 'auto', block: 'center' });
                c.style.scrollSnapType = 'none';
                c.style.scrollBehavior = 'auto';
            }
            const cards = document.querySelectorAll('#carousel .clip-card');
            if (cards.length > 0) {
                cards[0].scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'instant' });
            }
        }""")
        
        # Preload and wait until videos are ready and playing
        await page2.wait_for_timeout(600)
        
        # ─────────────────────────────────────────────────────────────
        # MARK T_START FOR PART 2 (Start timing exactly here!)
        # ─────────────────────────────────────────────────────────────
        t_results_ready = time.time()
        trim_offset_2 = t_results_ready - t_start_c2
        print(f"Part 2 results ready at offset {trim_offset_2:.3f}s", flush=True)
        
        # Hold on Card #1 for exactly 1.20s
        print("Part 2: Card #1 centered (1.20s)...", flush=True)
        await page2.wait_for_timeout(1200)
        
        # Jump cut to Card #2
        print("Part 2: Jump cut to Card #2 (1.20s)...", flush=True)
        await page2.evaluate("""() => {
            const cards = document.querySelectorAll('#carousel .clip-card');
            if (cards.length > 1) {
                cards[1].scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'instant' });
                cards[1].classList.add('is-previewing');
            }
        }""")
        await page2.wait_for_timeout(1200)
        
        # Jump cut to Card #3
        print("Part 2: Jump cut to Card #3 (1.20s)...", flush=True)
        await page2.evaluate("""() => {
            const cards = document.querySelectorAll('#carousel .clip-card');
            if (cards.length > 2) {
                cards[2].scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'instant' });
                cards[2].classList.add('is-previewing');
            }
        }""")
        await page2.wait_for_timeout(1200)
        
        # Jump cut to Card #4
        print("Part 2: Jump cut to Card #4 (3.20s)...", flush=True)
        await page2.evaluate("""() => {
            const cards = document.querySelectorAll('#carousel .clip-card');
            if (cards.length > 3) {
                cards[3].scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'instant' });
                cards[3].classList.add('is-previewing');
            }
        }""")
        await page2.wait_for_timeout(3200)
        
        await context2.close()
        await browser.close()
        print("Part 2 recorded cleanly!", flush=True)

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: Trim Part 1 to 6.00s and Part 2 to 6.80s, then Concat
    # ═══════════════════════════════════════════════════════════════
    webms_1 = [f for f in os.listdir(raw_dir_1) if f.endswith(".webm")]
    webms_2 = [f for f in os.listdir(raw_dir_2) if f.endswith(".webm")]
    
    if not webms_1 or not webms_2:
        raise RuntimeError("Failed to find recorded webm files!")
        
    raw_1 = os.path.join(raw_dir_1, webms_1[0])
    raw_2 = os.path.join(raw_dir_2, webms_2[0])
    
    print(f"Trimming Part 1: start {trim_offset_1:.3f}s, duration 6.000s...", flush=True)
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{trim_offset_1:.3f}",
        "-t", "6.0",
        "-i", raw_1,
        "-vf", "scale=1080:2340:flags=lanczos",
        "-r", "60",
        "-c:v", "libx264",
        "-crf", "14",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        part1_trimmed
    ], check=True)
    
    print(f"Trimming Part 2: start {trim_offset_2:.3f}s, duration 6.800s...", flush=True)
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{trim_offset_2:.3f}",
        "-t", "6.8",
        "-i", raw_2,
        "-vf", "scale=1080:2340:flags=lanczos",
        "-r", "60",
        "-c:v", "libx264",
        "-crf", "14",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        part2_trimmed
    ], check=True)
    
    print(f"Concatenating Part 1 + Part 2 -> {final_output} (Exact duration: 12.800s)...", flush=True)
    subprocess.run([
        "ffmpeg", "-y",
        "-i", part1_trimmed,
        "-i", part2_trimmed,
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
        "-map", "[v]",
        "-r", "60",
        "-c:v", "libx264",
        "-crf", "14",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        final_output
    ], check=True)
    
    print("Master recording generated successfully at:", final_output, flush=True)

if __name__ == "__main__":
    asyncio.run(record_masterpiece_full())
