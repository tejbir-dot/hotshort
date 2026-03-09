"""
Professional YouTube Cookies Manager
=====================================

This module provides professional-grade cookie handling for yt-dlp:
- Automatic validation and cache checking
- Graceful fallback mechanisms
- Professional logging
- Cookie freshness tracking
- Error recovery strategies

Based on yt-dlp best practices:
https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies
"""

import os
import json
import logging
import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

log = logging.getLogger(__name__)

# Constants
COOKIES_FILE = "cookies.txt"
COOKIES_METADATA_FILE = ".cookies_metadata.json"
COOKIE_FRESHNESS_DAYS = 14  # YouTube cookies expire ~2 weeks
WARNING_THRESHOLD_DAYS = 3  # Warn if cookies expire in <3 days


class YouTubeCookieManager:
    """Professional YouTube cookie manager for yt-dlp downloads."""

    def __init__(self, app_dir: str = None):
        """
        Initialize cookie manager.
        
        Args:
            app_dir: Base directory for storing cookies (defaults to current dir)
        """
        self.app_dir = Path(app_dir or os.getcwd())
        self.cookies_path = self.app_dir / COOKIES_FILE
        self.metadata_path = self.app_dir / COOKIES_METADATA_FILE
        self.is_valid = False
        self.last_error = None
        self._validate_cookies()

    def _validate_cookies(self) -> bool:
        """
        Validate cookies file exists and is not corrupted.
        
        Returns:
            True if valid cookies exist, False otherwise
        """
        try:
            if not self.cookies_path.exists():
                log.debug("Cookies file not found at %s", self.cookies_path)
                self.is_valid = False
                return False

            # Check file size (empty file is invalid)
            if self.cookies_path.stat().st_size < 100:
                log.warning("Cookies file too small (likely corrupted): %s", self.cookies_path)
                self.is_valid = False
                return False

            # Check for required headers
            with open(self.cookies_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'Netscape HTTP Cookie File' not in content:
                    log.warning("Invalid cookies file format (missing Netscape header)")
                    self.is_valid = False
                    return False
                if 'youtube.com' not in content:
                    log.warning("No YouTube cookies found in cookies file")
                    self.is_valid = False
                    return False

            log.info("✅ Cookies file validated: %s", self.cookies_path)
            self.is_valid = True
            return True

        except Exception as e:
            log.error("Error validating cookies: %s", e)
            self.last_error = str(e)
            self.is_valid = False
            return False

    def get_freshness_info(self) -> Dict:
        """Get cookie freshness information."""
        try:
            if self.metadata_path.exists():
                with open(self.metadata_path, 'r') as f:
                    metadata = json.load(f)
                    created_at = datetime.fromisoformat(metadata.get('created_at', ''))
                    expires_at = created_at + timedelta(days=COOKIE_FRESHNESS_DAYS)
                    days_remaining = (expires_at - datetime.now()).days
                    
                    return {
                        'created_at': metadata.get('created_at'),
                        'expires_at': expires_at.isoformat(),
                        'days_remaining': days_remaining,
                        'needs_refresh': days_remaining < WARNING_THRESHOLD_DAYS,
                        'is_expired': days_remaining < 0,
                    }
        except Exception as e:
            log.debug("Could not read cookies metadata: %s", e)
        
        return {
            'created_at': None,
            'expires_at': None,
            'days_remaining': None,
            'needs_refresh': False,
            'is_expired': False,
        }

    def save_usage_metadata(self) -> None:
        """Save metadata about when cookies were extracted."""
        try:
            metadata = {
                'created_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(days=COOKIE_FRESHNESS_DAYS)).isoformat(),
                'app_version': '1.0.0',
                'platform': sys.platform,
            }
            with open(self.metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            log.debug("Saved cookies metadata")
        except Exception as e:
            log.warning("Could not save cookies metadata: %s", e)

    def get_ydl_opts_fragment(self) -> Dict:
        """
        Get yt-dlp options fragment for cookie handling.
        
        Returns:
            Dictionary of yt-dlp options to merge into main options
        """
        opts = {
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            "geo_bypass": True,
            "geo_bypass_country": "US",
            "extractor_args": {
                "youtube": {
                    "player_client": ["web"],
                    "player_skip": ["js"],
                },
            },
            "socket_timeout": 30,
            "youtube_include_dash_manifest": False,
            "retries": 5,
            "fragment_retries": 5,
            "sleep_interval": 5,
            "max_sleep_interval": 15,
        }

        # Add cookies only if valid
        if self.is_valid:
            opts["cookiefile"] = str(self.cookies_path)
            log.debug("Using cookies from: %s", self.cookies_path)
        else:
            log.warning(
                "Cookies not available (may cause 'not a bot' errors). "
                "Run: python setup_youtube_cookies.py"
            )

        return opts

    def validate_and_report(self) -> Tuple[bool, str]:
        """
        Validate cookies and provide professional report.
        
        Returns:
            Tuple of (is_valid, report_message)
        """
        self._validate_cookies()
        freshness = self.get_freshness_info()

        if not self.is_valid:
            return False, (
                "❌ YouTube cookies not found or invalid.\n"
                "Run this to set up: python setup_youtube_cookies.py\n"
                "See https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies"
            )

        if freshness['is_expired']:
            return False, (
                f"⚠️ YouTube cookies EXPIRED (extracted ~{abs(freshness['days_remaining'])} days ago).\n"
                "Please refresh: python setup_youtube_cookies.py"
            )

        if freshness['needs_refresh']:
            days = freshness['days_remaining']
            return True, (
                f"⏰ YouTube cookies will expire in {days} day(s).\n"
                f"Consider refreshing soon: python setup_youtube_cookies.py"
            )

        days = freshness['days_remaining']
        return True, (
            f"✅ YouTube cookies valid ({days} day(s) remaining). "
            f"Next refresh: {freshness['expires_at']}"
        )

    def export_from_browser(self, browser: str = "chrome") -> bool:
        """
        Professional method to export cookies from browser.
        
        Args:
            browser: Browser name (chrome, edge, firefox, safari)
        
        Returns:
            True if export successful, False otherwise
        """
        log.info("🔄 Exporting YouTube cookies from %s browser...", browser)

        try:
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--cookies-from-browser",
                browser,
                "--cookies",
                str(self.cookies_path),
                "--extract-flat",
                "https://www.youtube.com/feed/home",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                log.info("✅ Cookies extracted successfully from %s", browser)
                self.save_usage_metadata()
                self._validate_cookies()
                return True
            else:
                error_msg = result.stderr or result.stdout
                log.error("❌ Cookie export failed: %s", error_msg)
                return False

        except subprocess.TimeoutExpired:
            log.error("❌ Cookie export timed out (>60s)")
            return False
        except FileNotFoundError:
            log.error(
                "❌ yt-dlp not found. Install with: pip install -U yt-dlp"
            )
            return False
        except Exception as e:
            log.error("❌ Unexpected error during cookie export: %s", e)
            return False


# Global instance
_cookie_manager: Optional[YouTubeCookieManager] = None


def get_cookie_manager(app_dir: str = None) -> YouTubeCookieManager:
    """Get or create global cookie manager instance."""
    global _cookie_manager
    if _cookie_manager is None:
        _cookie_manager = YouTubeCookieManager(app_dir)
    return _cookie_manager


def log_cookie_status() -> None:
    """Log current cookie status for startup diagnostics."""
    manager = get_cookie_manager()
    is_valid, report = manager.validate_and_report()
    
    if is_valid:
        log.info("💾 %s", report)
    else:
        log.warning("💾 %s", report)
