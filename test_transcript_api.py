from youtube_transcript_api import YouTubeTranscriptApi
import sys

video_id = "UELRn32cAhM"
try:
    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US', 'en-GB'])
    print(f"Fetched {len(transcript)} segments via API")
    print(transcript[:2])
except Exception as e:
    print(f"Failed: {e}")
