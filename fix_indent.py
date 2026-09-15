import re

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''                elif seg.mode == "ACTIVE_CENTER":
                      crop_h = max(2, int(src_h / 1.15)) & ~1
                      crop_w = max(2, int(round(crop_h * dst_ar))) & ~1
                    c_x = int(round(_clamp(seg.crop_x - crop_w / 2.0, 0.0, src_w - crop_w))) & ~1'''

replacement = '''                elif seg.mode == "ACTIVE_CENTER":
                    crop_h = max(2, int(src_h / 1.15)) & ~1
                    crop_w = max(2, int(round(crop_h * dst_ar))) & ~1
                    c_x = int(round(_clamp(seg.crop_x - crop_w / 2.0, 0.0, src_w - crop_w))) & ~1'''

content = content.replace(target, replacement)

with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
    f.write(content)
