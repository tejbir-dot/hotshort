path = r'c:\Users\n\Documents\hotshort\app.py'
with open(path, 'rb') as f:
    data = f.read()

# Find the export_all function block
marker = b'@app.route("/api/export_all", methods=["POST"])'
if marker not in data:
    print('MARKER NOT FOUND'); exit()

start_idx = data.index(marker)
# Find end of function - next route decorator or end of file
end_marker = b'from sqlalchemy.exc import OperationalError'
if end_marker not in data:
    print('END MARKER NOT FOUND'); exit()
end_idx = data.index(end_marker)

new_fn = b'''@app.route("/api/export_all", methods=["POST"])
@login_required
def export_all():
    try:
        data = request.json
        job_id = data.get("job_id")
        format_type = data.get("format", "tiktok")

        if not job_id:
            return jsonify({"error": "Job ID required"}), 400

        job_q = Job.query.filter_by(id=job_id)
        if not app.config.get("LOGIN_DISABLED"):
            job_q = job_q.filter_by(user_id=getattr(current_user, "id", None))
        job = job_q.first()
        if not job:
            return jsonify({"error": "Job not found"}), 404

        # Read clips from analysis_data JSON (where they actually live)
        import json as _json
        import urllib.request as _urlreq
        clip_list = []
        try:
            if job.analysis_data:
                raw = _json.loads(job.analysis_data)
                if isinstance(raw, dict) and "clips" in raw:
                    clip_list = raw.get("clips") or []
                elif isinstance(raw, list):
                    clip_list = raw
        except Exception as _e:
            log.warning("[EXPORT-ALL] Failed to parse analysis_data: %s", _e)

        if not clip_list:
            return jsonify({"error": "No clips found for this job"}), 404

        export_dir = os.path.join(BASE_DIR, "static", "exports")
        os.makedirs(export_dir, exist_ok=True)

        batch_id = str(uuid.uuid4())[:8]
        zip_filename = f"batch_{format_type}_{job_id}_{batch_id}.zip"
        zip_path = os.path.join(export_dir, zip_filename)

        added = 0
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            for idx, clip in enumerate(clip_list):
                clip_url = (
                    clip.get("clip_url")
                    or clip.get("video_url")
                    or clip.get("url")
                    or ""
                ).strip()
                if not clip_url:
                    log.warning("[EXPORT-ALL] clip %s has no URL, skipping", idx)
                    continue

                title_raw = clip.get("title") or f"clip_{idx + 1}"
                title_safe = re.sub(r"[^\\w\\-_ ]", "_", title_raw)[:60]
                clip_filename = f"{idx + 1:02d}_{title_safe}.mp4"

                try:
                    req = _urlreq.Request(clip_url, headers={"User-Agent": "HotShort/1.0"})
                    with _urlreq.urlopen(req, timeout=60) as resp:
                        zipf.writestr(clip_filename, resp.read())
                    added += 1
                    log.info("[EXPORT-ALL] Added %s", clip_filename)
                except Exception as _e:
                    log.warning("[EXPORT-ALL] Failed to fetch clip %s (%s): %s", idx, clip_url, _e)

        if added == 0:
            try:
                os.remove(zip_path)
            except Exception:
                pass
            return jsonify({"error": "No clips could be downloaded - URLs may have expired"}), 502

        log.info("[EXPORT-ALL] zip ready: %s (%d clips)", zip_filename, added)
        return jsonify({"url": f"/static/exports/{zip_filename}", "success": True, "clips_added": added})

    except Exception as e:
        app.logger.exception("Batch export failed")
        return jsonify({"error": str(e)}), 500

'''

data = data[:start_idx] + new_fn + data[end_idx:]
with open(path, 'wb') as f:
    f.write(data)
print('export_all FIXED OK')
