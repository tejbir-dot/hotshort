import { chromium, devices } from "playwright";
import * as path from "path";
import * as fs from "fs";
import { execSync } from "child_process";

async function recordYouTube() {
  const iphone = devices["iPhone 15 Pro"];
  const rawDir = path.resolve(__dirname, "temp_rec");
  if (!fs.existsSync(rawDir)) fs.mkdirSync(rawDir, { recursive: true });

  const finalOutput = path.resolve(__dirname, "public/yt_search.mp4");

  const browser = await chromium.launch({
    headless: true,
  });

  const context = await browser.newContext({
    ...iphone,
    viewport: { width: 393, height: 852 },
    deviceScaleFactor: 3,
    colorScheme: "dark",
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    recordVideo: {
      dir: rawDir,
      size: { width: 393, height: 852 },
    },
  });

  const page = await context.newPage();

  console.log("Navigating to m.youtube.com...");
  await page.goto("https://m.youtube.com", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  // Accept consent if shown
  try {
    const consent = await page.$(
      "button[aria-label*='Accept'], button:has-text('Accept all'), button:has-text('I agree')"
    );
    if (consent) {
      await consent.click();
      await page.waitForTimeout(1000);
    }
  } catch {}

  // Open search and type 'ishowspeed' at 60ms/char
  console.log("Typing 'ishowspeed' at 60ms per char...");
  const searchInput = await page.$(
    "input[name='search'], input[type='search'], input.search-input"
  );
  if (searchInput) {
    await searchInput.focus();
    await page.keyboard.type("ishowspeed", { delay: 60 });
    await page.keyboard.press("Enter");
  } else {
    await page.goto("https://m.youtube.com/results?search_query=ishowspeed");
  }

  await page.waitForTimeout(2500);

  // Realistic wheel/touch inertia scroll
  console.log("Scrolling with inertia...");
  const scrollSteps = [25, 50, 75, 95, 110, 100, 80, 50, 20, 5];
  for (const delta of scrollSteps) {
    await page.mouse.wheel(0, delta);
    await page.waitForTimeout(60);
  }

  await page.waitForTimeout(1500);

  // Tap video
  console.log("Tapping video...");
  const video = await page.$(
    "ytd-video-renderer, ytm-video-with-context-renderer, a.media-item-thumbnail-container"
  );
  if (video) {
    await video.click();
  } else {
    await page.mouse.click(200, 360);
  }

  await page.waitForTimeout(2500);

  // Open Share Sheet
  console.log("Opening Share sheet...");
  const shareBtn = await page.$(
    "button[aria-label*='Share'], button:has-text('Share')"
  );
  if (shareBtn) {
    await shareBtn.click();
    await page.waitForTimeout(1500);

    const copyBtn = await page.$(
      "button:has-text('Copy link'), button[aria-label*='Copy link']"
    );
    if (copyBtn) {
      await copyBtn.click();
      await page.waitForTimeout(1000);
    }
  }

  await context.close();
  await browser.close();

  // Find recorded video and convert to 60fps MP4
  const webms = fs.readdirSync(rawDir).filter((f) => f.endsWith(".webm"));
  if (webms.length > 0) {
    const rawWebm = path.join(rawDir, webms[0]);
    execSync(
      `ffmpeg -y -i "${rawWebm}" -r 60 -c:v libx264 -crf 18 -pix_fmt yuv420p "${finalOutput}"`
    );
    console.log(`Saved 60fps recording to ${finalOutput}`);
  }
}

recordYouTube().catch(console.error);
