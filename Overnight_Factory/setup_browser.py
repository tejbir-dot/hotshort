import asyncio
from playwright.async_api import async_playwright

# ⚙️ TERA PROXY DATA (Jo tune mujhe pehle diya tha)
PROXY_IP = "162.210.64.27"
PROXY_PORT = "12323"
PROXY_USER = "14a930ebcafee"
PROXY_PASS = "e269d4d909"

# 📂 Yahan tera apna "Dolphin" profile save hoga
PROFILE_DIR = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Ghost_Profile"

async def setup():
    async with async_playwright() as p:
        print("🌐 Launching OUR OWN Ghost Browser...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel="chrome", # Asli Google Chrome use karega
            headless=False,
            proxy={
                "server": f"http://{PROXY_IP}:{PROXY_PORT}",
                "username": PROXY_USER,
                "password": PROXY_PASS
            },
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        print("\n✅ BROWSER KHUL GAYA HAI! (Tera Proxy Inject ho chuka hai)")
        print("👉 Ab is browser mein YouTube, TikTok, aur Instagram khol aur apna US wala account login kar le.")
        print("⏳ Tere paas 10 minute hain. Aaram se login kar, tab tak browser open rahega...\n")
        
        await asyncio.sleep(600) # 10 minute ka wait
        await context.close()
        print("🚪 Logins Saved Permanently!")

if __name__ == "__main__":
    asyncio.run(setup())
