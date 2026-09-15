import time
import os
from faster_whisper import WhisperModel

def test_transcription():
    # Use the same model logic as runpodworker
    print("Loading model...")
    model = WhisperModel("medium", device="cuda", compute_type="int8_float16")
    audio_path = "test_slice.mp4" # using test_slice since it's available

    # Check if the file exists
    if not os.path.exists(audio_path):
        print(f"Error: {audio_path} not found. Please provide a valid video.")
        return

    # Run WITHOUT word_timestamps (Baseline)
    print("\nRunning Baseline (word_timestamps=False)...")
    start_time = time.time()
    segments_baseline, _ = model.transcribe(
        audio_path,
        beam_size=2,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=False,
    )
    # exhaust generator to actually run transcription
    list(segments_baseline) 
    time_baseline = time.time() - start_time
    print(f"Baseline Time: {time_baseline:.2f} seconds")

    # Run WITH word_timestamps
    print("\nRunning New Config (word_timestamps=True)...")
    start_time = time.time()
    segments_new, _ = model.transcribe(
        audio_path,
        beam_size=2,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=True,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4
    )
    segments_list = list(segments_new)
    time_new = time.time() - start_time
    print(f"New Config Time: {time_new:.2f} seconds")
    
    overhead = ((time_new - time_baseline) / time_baseline) * 100
    print(f"\nTiming Overhead: {overhead:.1f}%")

    # Print sample data
    print("\nSample Segment Data (First Segment):")
    if len(segments_list) > 0:
        first_seg = segments_list[0]
        print(f"Segment Start: {first_seg.start:.2f}, End: {first_seg.end:.2f}, Text: '{first_seg.text}'")
        print("Words Array:")
        if hasattr(first_seg, 'words') and first_seg.words:
            for w in first_seg.words[:10]: # Print first 10 words
                print(f"  [{w.start:.2f} -> {w.end:.2f}] '{w.word}' (prob: {getattr(w, 'probability', 1.0):.2f})")
        else:
            print("  NO WORDS ARRAY FOUND")

if __name__ == "__main__":
    test_transcription()
