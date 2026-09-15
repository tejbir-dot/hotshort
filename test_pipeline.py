import os
import json
import asyncio
from viral_finder.orchestrator import orchestrate

# Force the exact environment variables that caused the log you pasted
os.environ['HS_EXPERIMENT_MODE'] = '1'
os.environ['HS_GROQ_CORTEX_ENABLED'] = '1'
os.environ['HS_GROQ_TRANSCRIPT_FIRST'] = '0'
os.environ['HS_GROQ_NARRATIVE_ROLES'] = '0'
os.environ['HS_USE_CLIP_COMPILER'] = '1'

# Point this to whatever fake path is needed to load the cache, 
# Point this to whatever fake path is needed to load the cache, 
# or directly pass the same mock video you've been using.
test_video_path = "test_slice.mp4"
payload = {
    'video_url': 'https://www.youtube.com/watch?v=mock',
    'options': {
        'transcript_first': False,
        'cortex_enabled': True,
        'narrative_roles': False
    }
}

def main():
    print('Starting pipeline test...')
    try:
        result = orchestrate(test_video_path, top_k=6)
        print('Pipeline completed successfully!')
        print(f'Total final clips: {len(result)}')
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
