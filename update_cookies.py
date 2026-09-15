import browser_cookie3
import http.cookiejar
import os

def update_cookies():
    print("Extracting YouTube cookies from Firefox...")
    try:
        # Extract cookies specifically for youtube.com from Firefox
        c = browser_cookie3.firefox(domain_name='.youtube.com')
        
        # Save them in the Netscape format that yt-dlp requires
        cj = http.cookiejar.MozillaCookieJar('cookies.txt')
        for cookie in c:
            cj.set_cookie(cookie)
        cj.save()
        
        print("✅ Success! Cookies saved to 'cookies.txt'.")
        print("local_worker.py will now use these cookies to bypass YouTube's bot detection.")
        
    except Exception as e:
        print(f"❌ Failed to extract cookies: {e}")
        print("Make sure Firefox is installed and you have logged into YouTube recently.")

if __name__ == "__main__":
    update_cookies()
