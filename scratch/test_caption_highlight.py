import sys
import os
import re

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from effects.world_class_editor import ClipEditor

def test_highlighting():
    editor = ClipEditor(work_dir="temp_test_dir")
    
    # Test cases
    cases = [
        # Standard sentence - no priority keywords, should highlight longest word ("engineering")
        ("This is a video engineering prototype", "This is a video {\\rHighlight}engineering{\\r} prototype"),
        
        # Sentence with priority keywords (should highlight up to 2 priority keywords)
        ("This secret will make you rich and viral", "This {\\rHighlight}secret{\\r} will make you rich and {\\rHighlight}viral{\\r}"),
        
        # Sentence with 2 priority keywords (should highlight both "Stop" and "mistake")
        ("Stop doing this mistake now", "{\\rHighlight}Stop{\\r} doing this {\\rHighlight}mistake{\\r} now"),
        
        # Word with punctuation
        ("growth is key.", "{\\rHighlight}growth{\\r} is key."),
    ]
    
    success = True
    for inp, expected in cases:
        out = editor._highlight_text(inp)
        if out == expected:
            print(f"✅ Pass: '{inp}' -> '{out}'")
        else:
            print(f"❌ Fail: '{inp}'\n  Got:      '{out}'\n  Expected: '{expected}'")
            success = False
            
    if success:
        print("\n🎉 All highlight logic unit tests passed successfully!")
    else:
        sys.exit(1)

if __name__ == "__main__":
    test_highlighting()
