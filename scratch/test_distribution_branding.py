import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_worker import _apply_distribution_branding

def test_branding():
    input_vid = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_slice.mp4")
    output_vid = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dummy_branded.mp4")
    
    if not os.path.exists(input_vid):
        print(f"Missing input video: {input_vid}")
        return
        
    print(f"Testing branding with input: {input_vid}")
    success = _apply_distribution_branding(input_vid, output_vid)
    print(f"Branding Success: {success}")
    if os.path.exists(output_vid):
        print(f"Output generated successfully: {output_vid}")

if __name__ == "__main__":
    test_branding()
