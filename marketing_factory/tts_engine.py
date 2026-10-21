import os
import asyncio
import edge_tts
import whisper

async def synthesize_edge_tts(text, voice="en-US-ChristopherNeural", output_audio_path="scratch/marketing_factory/voice.mp3"):
    os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)
    comm = edge_tts.Communicate(text, voice)
    await comm.save(output_audio_path)
    return output_audio_path

def get_word_timestamps(audio_path, model_name="base"):
    """
    Runs whisper on the generated TTS audio to get precise word-level timestamps.
    """
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, word_timestamps=True)
    
    words = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            clean_word = w["word"].strip()
            if clean_word:
                words.append({
                    "word": clean_word,
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3)
                })
    return words

def group_words_into_captions(words, max_words=2):
    """
    Groups individual words into punchy 1-3 word caption chunks.
    """
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i : i + max_words]
        text = " ".join([w["word"] for w in chunk_words])
        start = chunk_words[0]["start"]
        end = chunk_words[-1]["end"]
        chunks.append({
            "text": text,
            "start": start,
            "end": end
        })
        i += max_words
    return chunks

def generate_voiceover(text, voice="en-US-ChristopherNeural", output_path="scratch/marketing_factory/voice.mp3"):
    asyncio.run(synthesize_edge_tts(text, voice=voice, output_audio_path=output_path))
    words = get_word_timestamps(output_path)
    chunks = group_words_into_captions(words, max_words=2)
    return output_path, chunks

if __name__ == "__main__":
    test_text = "Here is how I make viral clips that get millions of views."
    path, chunks = generate_voiceover(test_text)
    print("Voice generated at:", path)
    print(f"Chunks ({len(chunks)}):", chunks)
