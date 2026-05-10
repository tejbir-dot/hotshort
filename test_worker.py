from runpodworker import handler

event = {
    "input": {
        "task": "orchestrate",
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
}

result = handler(event)

print("\n=== RESULT ===")
print(result)