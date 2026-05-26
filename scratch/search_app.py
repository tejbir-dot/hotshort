with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.read().splitlines()
    
target_lines = [3160, 3161, 3162, 3163, 3164, 3165, 3166, 3167, 3168, 3175, 3176, 3177, 3178, 3179, 3180, 3181, 3182, 3183, 3225, 3226, 3227, 3228, 3229, 3230, 3231, 3232, 3233, 3545, 3546, 3547, 3548, 3549, 3550, 3551, 3552, 3553, 3560, 3561, 3562, 3563, 3564, 3565, 3566, 3567, 3568]
for idx in target_lines:
    if idx <= len(lines):
        safe_line = lines[idx-1].encode('ascii', errors='replace').decode('ascii')
        print(f"Line {idx}: {safe_line}")
