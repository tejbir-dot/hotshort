#!/usr/bin/env python3
"""
Professional YouTube Cookies Setup
===================================

This script provides a professional, production-grade method to export YouTube 
cookies for use with yt-dlp, eliminating "Sign in to confirm you're not a bot" 
errors.

Based on official yt-dlp best practices:
https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies

Features:
---------
- Automatic browser detection and cookie extraction
- Validation of extracted cookies
- Automatic cookie rotation every 2 weeks
- Professional status reporting
- Integration with hotshort app

Usage:
------
  python setup_youtube_cookies.py [browser]
  
  browser: Optional. (chrome|edge|firefox|safari)
  If not specified, you'll be prompted to choose.

Examples:
---------
  python setup_youtube_cookies.py
  python setup_youtube_cookies.py chrome
  python setup_youtube_cookies.py firefox
"""

import sys
import os
from pathlib import Path

# Try to import the professional cookie manager
try:
    from youtube_cookie_manager import YouTubeCookieManager
    HAS_COOKIE_MANAGER = True
except ImportError:
    HAS_COOKIE_MANAGER = False


def print_header():
    """Print pretty header."""
    print("\n" + "=" * 75)
    print("Professional YouTube Cookies Setup".center(75))
    print("=" * 75 + "\n")


def print_section(title):
    """Print section header."""
    print(f"\n📋 {title}")
    print("-" * 75)


def get_browser_choice():
    """Interactive browser selection."""
    browsers = [
        ("Chrome/Chromium", "chrome"),
        ("Microsoft Edge", "edge"),
        ("Mozilla Firefox", "firefox"),
        ("Safari (macOS)", "safari"),
    ]

    print("\n🌐 Available Browsers:")
    for i, (name, code) in enumerate(browsers, 1):
        print(f"   {i}. {name:20s} ({code})")

    while True:
        choice = input("\nSelect your browser (1-4): ").strip()
        if choice in ["1", "2", "3", "4"]:
            idx = int(choice) - 1
            return browsers[idx][1], browsers[idx][0]
        print("❌ Invalid choice. Please enter 1-4.")


def main():
    """Main setup flow."""
    print_header()

    # Check if cookie manager is available
    if not HAS_COOKIE_MANAGER:
        print("⚠️ Cookie manager not available. Using fallback mode.\n")
        fallback_setup()
        return

    # Use professional cookie manager
    app_dir = Path(__file__).parent
    manager = YouTubeCookieManager(app_dir)

    # Show current status
    print_section("Current Status")
    is_valid, report = manager.validate_and_report()
    print(report)

    # Decide what to do
    if is_valid:
        freshness = manager.get_freshness_info()
        days_left = freshness.get('days_remaining') or 0

        if days_left > 7:
            print("\n✅ Your cookies are fresh and valid.")
            choice = input("\nRefresh anyway? (y/n): ").strip().lower()
            if choice != 'y':
                print("\n✨ Setup complete! Your cookies are valid.")
                return

    # Get browser choice
    print_section("Browser Selection")
    print("\n📌 You must be logged into YouTube in your browser.\n")
    browser_code, browser_name = get_browser_choice()

    # Start extraction
    print_section("Extracting Cookies")
    print(f"\n🔄 Extracting cookies from {browser_name}...")
    print("   (This may take 30-60 seconds...)\n")

    success = manager.export_from_browser(browser_code)

    if success:
        print_section("✅ Success!")
        is_valid, report = manager.validate_and_report()
        print(report)
        print("\n🎉 Your app will now automatically use these cookies!")
        print("💡 Reminder: Refresh cookies every 2 weeks for best results.\n")
    else:
        print_section("❌ Extraction Failed")
        print("\nTroubleshooting:\n")
        print("1. Make sure you're logged into YouTube in your browser")
        print("2. Make sure yt-dlp is installed: pip install -U yt-dlp")
        print("3. Try a different browser\n")

        print("Manual Alternative (Professional Method):\n")
        print("   Option A - Extract directly from browser:")
        print(f"   yt-dlp --cookies-from-browser {browser_code} \\")
        print("        --cookies cookies.txt https://www.youtube.com\n")

        print("   Option B - Use netscape cookie export:")
        print("   (See: https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)\n")


def fallback_setup():
    """Fallback setup without cookie manager."""
    print("⚠️ Fallback Setup Mode\n")

    print("This script will guide you through manual cookie extraction.\n")

    print("Requirements:")
    print("- Logged-in YouTube session in your browser")
    print("- yt-dlp installed: pip install -U yt-dlp\n")

    # Get browser choice
    print("Select your browser:")
    browsers = [
        ("Chrome/Chromium", "chrome"),
        ("Microsoft Edge", "edge"),
        ("Firefox", "firefox"),
        ("Safari", "safari"),
    ]

    for i, (name, code) in enumerate(browsers, 1):
        print(f"  {i}. {name}")

    while True:
        choice = input("\nEnter choice (1-4): ").strip()
        if choice in ["1", "2", "3", "4"]:
            browser_code = browsers[int(choice) - 1][1]
            break
        print("Invalid choice, try again.")

    print("\n" + "=" * 75)
    print("Running cookie extraction...".center(75))
    print("=" * 75 + "\n")

    cmd = f"yt-dlp --cookies-from-browser {browser_code} --cookies cookies.txt https://www.youtube.com"

    print(f"Command: {cmd}\n")
    print("(Press ENTER to continue or CTRL+C to cancel)\n")
    input()

    os.system(cmd)

    print("\n" + "=" * 75)
    print("Setup Complete".center(75))
    print("=" * 75)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            # Browser provided as argument
            browser = sys.argv[1].lower().strip()
            if browser not in ["chrome", "edge", "firefox", "safari"]:
                print(f"Error: Invalid browser '{browser}'")
                print("Valid options: chrome, edge, firefox, safari")
                sys.exit(1)

            app_dir = Path(__file__).parent
            manager = YouTubeCookieManager(app_dir)
            print_header()
            print(f"🔄 Extracting cookies from {browser}...\n")
            success = manager.export_from_browser(browser)

            if success:
                print("\n✅ Success!")
                is_valid, report = manager.validate_and_report()
                print(report)
            else:
                print("\n❌ Extraction failed!")
                sys.exit(1)
        else:
            # Interactive mode
            main()

    except KeyboardInterrupt:
        print("\n\n⚠️ Setup cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

