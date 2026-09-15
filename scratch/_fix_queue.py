import re

with open('local_worker.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace Producer side
old_producer = '''                    with ThreadPoolExecutor(max_workers=4) as ex:
                        futures = [ex.submit(gen_cap, c, i) for i, c in enumerate(clips)]
                        for future in futures:
                            idx, ass_path = future.result()
                            precomputed_captions[idx] = ass_path

                for i, clip in enumerate(clips):
                    clip_queue.put((i, clip))
                    print(f"[PIPELINE] Clip queued: {i}", flush=True)'''

new_producer = '''                    ex = ThreadPoolExecutor(max_workers=4)
                    for i, c in enumerate(clips):
                        precomputed_captions[i] = ex.submit(gen_cap, c, i)

                for i, clip in enumerate(clips):
                    clip_queue.put((i, clip))
                    print(f"[PIPELINE] Clip queued: {i}", flush=True)'''

# Replace Consumer side
old_consumer = '''                                precomputed_ass_path=precomputed_captions.get(i)
                            )'''

new_consumer = '''                                precomputed_ass_path=precomputed_captions[i].result()[1] if precomputed_captions.get(i) else None
                            )'''

if old_producer in text and old_consumer in text:
    text = text.replace(old_producer, new_producer)
    text = text.replace(old_consumer, new_consumer)
    with open('local_worker.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched local_worker successfully!")
else:
    print("Failed to find strings to replace")
