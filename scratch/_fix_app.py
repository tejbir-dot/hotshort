with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if line.startswith('def process_video_hybrid('):
        new_lines.append(line)
        new_lines.append('    is_free_user = True\n')
        new_lines.append('    if job_id:\n')
        new_lines.append('        try:\n')
        new_lines.append('            job = Job.query.filter_by(id=job_id).first()\n')
        new_lines.append('            if job and job.user_id:\n')
        new_lines.append('                user = User.query.get(job.user_id)\n')
        new_lines.append('                if user:\n')
        new_lines.append('                    is_free_user = not get_free_status(user).get("is_paid")\n')
        new_lines.append('        except Exception:\n')
        new_lines.append('            pass\n')
        skip = True
    elif skip:
        if line.strip() == '"""' or line.startswith('    """'):
            skip = False
            new_lines.append(line)
    else:
        new_lines.append(line)

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Successfully updated app.py!")
