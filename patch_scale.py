import os

def patch_file(path, replacements):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in replacements:
        if old not in content:
            print(f"Warning: {old} not found in {path}")
        content = content.replace(old, new)
        
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Patched {path}")

# Patch local_worker.py
patch_file("local_worker.py", [
    ("scaleFactor=1.05,", "scaleFactor=1.15,"),
    ("'scaleFactor': 1.05,", "'scaleFactor': 1.15,")
])

# Patch effects/world_class_editor.py
patch_file("effects/world_class_editor.py", [
    ("cascade.detectMultiScale(gray, 1.05, 3, minSize=(40, 40))", "cascade.detectMultiScale(gray, 1.15, 3, minSize=(40, 40))"),
    ("scaleFactor=1.05,   # finer scale (was 1.1)", "scaleFactor=1.15,   # finer scale (was 1.1)")
])
