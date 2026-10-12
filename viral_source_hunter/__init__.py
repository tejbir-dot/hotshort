"""
Viral Source Hunter v1.0
=========================
Takes any viral short clip → Finds original long-form source → Downloads exact segment.

Pipeline:
  Layer 0: Signal Extraction   (frames + transcript + metadata + OCR)
  Layer 1: Source Identification (Gemini Vision + confidence scoring)
  Layer 2: Source Video Finder  (YouTube search + validation)
  Layer 3: Timestamp Alignment  (subtitle fuzzy + audio cross-correlation)
  Layer 4: Precision Download   (yt-dlp --download-sections)

Usage:
  python viral_source_hunter/hunter.py "viral_clip.mp4"
  python viral_source_hunter/hunter.py "https://youtube.com/shorts/XYZ"
"""
