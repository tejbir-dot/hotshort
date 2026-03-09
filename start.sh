#!/bin/bash

echo "Updating system..."
apt update

echo "Installing ffmpeg..."
apt install -y ffmpeg git

echo "Cloning repo..."
if [ ! -d "hotshort" ]; then
  git clone https://github.com/tejbir-dot/hotshort.git
fi

cd hotshort

echo "Installing python deps..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Installing extra libs..."
pip install faster-whisper yt-dlp sentence-transformers ffmpeg-python

echo ""
echo "=============================================================="
echo "⚠️  IMPORTANT: YouTube Bot-Check Bypass Setup"
echo "=============================================================="
echo ""
echo "To avoid 'Sign in to confirm you're not a bot' errors:"
echo ""
echo "Option 1 (Recommended - Automatic):"
echo "  python setup_youtube_cookies.py"
echo ""
echo "Option 2 (Manual):"
echo "  1. Log into YouTube in your browser"
echo "  2. Run: yt-dlp --cookies-from-browser chrome --cookies cookies.txt https://www.youtube.com"
echo "  3. (Replace 'chrome' with: edge, firefox, or safari)"
echo ""
echo "Cookies are valid for ~2 weeks. Refresh them when downloads start failing."
echo "=============================================================="
echo ""

echo "Starting HotShort AI engine..."
python app.py