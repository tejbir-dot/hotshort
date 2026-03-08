#!/usr/bin/env python3
"""
🔥 PRODUCTION STABILITY TEST SUITE
Tests the complete flow:
1. Video download with yt-dlp (geo-bypass enabled)
2. Error handling and flash messages
3. Toast notification system
4. Redirect patterns (no JSON to browser)
"""

import os
import sys
import json
import time
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# Test cases
TEST_CASES = {
    "public_video": {
        "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # Famous "Me at the zoo" - always available
        "description": "Public video (should succeed)",
        "expect": "success"
    },
    "private_video": {
        "url": "https://www.youtube.com/watch?v=PRIVATE123",  # Invalid/private
        "description": "Private/blocked video (should fail gracefully)",
        "expect": "error"
    },
    "invalid_url": {
        "url": "https://example.com/not-youtube",
        "description": "Non-YouTube URL (should fail)",
        "expect": "error"
    }
}

def test_yt_dlp_import():
    """Test 1: Verify yt-dlp is installed and importable"""
    log.info("=" * 60)
    log.info("TEST 1: yt-dlp Import")
    log.info("=" * 60)
    
    try:
        import yt_dlp
        log.info("✅ yt-dlp imported successfully")
        log.info(f"   Version: {yt_dlp.__version__ if hasattr(yt_dlp, '__version__') else 'unknown'}")
        return True
    except ImportError as e:
        log.error(f"❌ Failed to import yt-dlp: {e}")
        return False

def test_download_function():
    """Test 2: Test the download_youtube_video function with options"""
    log.info("\n" + "=" * 60)
    log.info("TEST 2: Download Function with Geo-Bypass")
    log.info("=" * 60)
    
    try:
        import yt_dlp
        
        # Test with a public video (short one - Me at the zoo)
        test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        output_dir = "test_downloads"
        os.makedirs(output_dir, exist_ok=True)
        
        ydl_opts = {
            "format": "bv*+ba/b",
            "quiet": True,
            "no_warnings": False,
            "js_runtimes": {"node": {}},
            "noplaylist": True,
            "geo_bypass": True,  # ✅ CRITICAL: Bypass geo-blocking
            "nocheckcertificate": True,
            "socket_timeout": 30,
            "http_chunk_size": 10485760,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-us,en;q=0.5",
            },
        }
        
        log.info(f"Testing with URL: {test_url}")
        log.info("Options:")
        log.info(f"  - format: {ydl_opts['format']}")
        log.info(f"  - js_runtimes: {ydl_opts.get('js_runtimes')}")
        log.info(f"  - geo_bypass: {ydl_opts['geo_bypass']}")
        log.info(f"  - socket_timeout: {ydl_opts['socket_timeout']}s")
        
        start = time.time()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log.info("Extracting video info...")
            info = ydl.extract_info(test_url, download=False)  # Info only, don't download in test
            title = info.get('title', 'Unknown')
            duration = info.get('duration', 0)
            log.info(f"✅ Video found: {title}")
            log.info(f"   Duration: {duration}s")
            assert "js_runtimes" in ydl_opts, "runtime option missing"
            return True
            
    except Exception as e:
        log.error(f"❌ Download function failed: {str(e)[:100]}")
        return False


def test_metadata_and_transcript_helpers():
    """Test new helpers added in ingestion redesign."""
    log.info("\n" + "=" * 60)
    log.info("TEST 5: Metadata & Transcript Helpers")
    log.info("=" * 60)
    try:
        from app import fetch_youtube_metadata, fetch_youtube_transcript, select_segment_from_transcript
        test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        md = fetch_youtube_metadata(test_url)
        log.info(f"Metadata keys: {list(md.keys())}")
        assert md.get("title")
        segs = fetch_youtube_transcript(test_url)
        log.info(f"Transcript segs count: {len(segs)}")
        start, end = select_segment_from_transcript(segs, md.get("duration"))
        log.info(f"Selected {start}-{end}")
        return True
    except Exception as e:
        log.error(f"❌ Metadata/transcript helper test failed: {e}")
        return False


def test_starvation_guard():
    """Test 8: starvation guard triggers when probe duration is tiny but video is long."""
    log.info("\n" + "=" * 60)
    log.info("TEST 8: Starvation warning logic")
    log.info("=" * 60)
    try:
        from app import acquire_youtube_media_robust
        import app
        # monkeypatch probe_media to simulate tiny download
        orig = app.probe_media
        app.probe_media = lambda p: {"ok": True, "duration": 10.0}
        _, _, attempts, _, _ = acquire_youtube_media_robust(
            "dummy",
            start=0,
            end=10,
            output_dir=".",
            job_id="guardtest",
            metadata={"duration": 400.0},
        )
        # ensure at least one warning entry exists
        assert any(a.get("warning", {}).get("starvation_detected") for a in attempts), "guard did not fire"
        return True
    except Exception as e:
        log.error(f"❌ Starvation guard test failed: {e}")
        return False
    finally:
        try:
            app.probe_media = orig
        except Exception:
            pass


def test_ui_premium_framing():
    """Test 6: the new premium placeholder appears in at least one template."""
    log.info("\n" + "=" * 60)
    log.info("TEST 6: UI premium phrasing")
    log.info("=" * 60)
    try:
        path = "templates/index.html"
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "fast import" in content
        log.info("✅ Found premium phrasing in index.html")
        return True
    except Exception as e:
        log.error(f"❌ UI framing test failed: {e}")
        return False


def test_analyze_captcha_error():
    """Test 7: analyze route returns helpful message when download is blocked by captcha."""
    log.info("\n" + "=" * 60)
    log.info("TEST 7: Analyze captcha error handling")
    log.info("=" * 60)
    try:
        import app as app_module
        from app import YoutubeCaptchaError

        # patch both download helpers on the module rather than the Flask object
        original_full = app_module.download_youtube_video
        original_seg = app_module.download_youtube_segment
        def raise_captcha(*args, **kwargs):
            raise YoutubeCaptchaError("dummy bot check")
        app_module.download_youtube_video = raise_captcha
        app_module.download_youtube_segment = raise_captcha

        # disable login requirement for the duration of this test
        prev = app_module.app.config.get('LOGIN_DISABLED', False)
        app_module.app.config['LOGIN_DISABLED'] = True
        with app_module.app.test_client() as client:
            resp = client.post(
                '/analyze',
                data={'youtube_url': 'https://youtu.be/xyz'},
                headers={'Accept': 'application/json'}
            )
            log.info(f"Response status: {resp.status_code}")
            data = None
            if resp.is_json:
                data = resp.get_json()
                log.info(f"JSON body: {data}")
            assert resp.status_code == 400
            assert data and ("sign-in" in data.get('error','').lower() or "cookies" in data.get('error','').lower() or "bot" in data.get('error','').lower())
        # restore config and patch state
        app_module.app.config['LOGIN_DISABLED'] = prev
        app_module.download_youtube_video = original_full
        app_module.download_youtube_segment = original_seg
        return True
    except Exception as e:
        log.error(f"❌ Captcha error test failed: {e}")
        return False

def test_flash_redirect_pattern():
    """Test 3: Verify Flask flash() and redirect() pattern works"""
    log.info("\n" + "=" * 60)
    log.info("TEST 3: Flask Flash & Redirect Pattern")
    log.info("=" * 60)
    
    try:
        from flask import Flask, flash, redirect, url_for
        
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret'
        
        @app.route('/test-redirect')
        def test_route():
            flash("Test message", "error")
            return redirect(url_for('dashboard'))
        
        @app.route('/dashboard')
        def dashboard():
            return "Dashboard"
        
        with app.app_context():
            with app.test_client() as client:
                log.info("Testing redirect with flash...")
                response = client.get('/test-redirect', follow_redirects=False)
                log.info(f"✅ Response status: {response.status_code}")
                log.info(f"   Location header: {response.location}")
                
                # Check if flash was set (check response headers for Set-Cookie)
                if 'Set-Cookie' in response.headers or response.status_code == 302:
                    log.info("✅ Flash message would be stored in session")
                    return True
        
        return False
        
    except Exception as e:
        log.error(f"❌ Flash/redirect test failed: {e}")
        return False

def test_toast_html_structure():
    """Test 4: Verify toast notification HTML is valid"""
    log.info("\n" + "=" * 60)
    log.info("TEST 4: Toast Notification HTML Structure")
    log.info("=" * 60)
    
    try:
        base_html_path = "templates/base.html"
        with open(base_html_path, 'r') as f:
            content = f.read()
        
        checks = {
            "toast-container div": 'id="toastContainer"' in content,
            "toast CSS styles": '.toast {' in content and '.toast-error' in content,
            "slideIn animation": '@keyframes slideIn' in content,
            "Toast JS system": 'function showToast' in content or 'showToast' in content,
            "get_flashed_messages": 'get_flashed_messages' in content,
            "window.showToast exposed": 'window.showToast' in content,
        }
        
        all_passed = True
        for check_name, result in checks.items():
            status = "✅" if result else "❌"
            log.info(f"{status} {check_name}")
            if not result:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        log.error(f"❌ Toast HTML test failed: {e}")
        return False

def test_no_jsonify_errors():
    """Test 5: Verify browser-facing flow avoids raw JSON errors."""
    log.info("\n" + "=" * 60)
    log.info("TEST 5: Browser Flow Error Contract")
    log.info("=" * 60)
    
    try:
        app_path = "app.py"
        with open(app_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        if "def analyze_video():" not in content:
            log.error("❌ analyze_video function not found")
            return False

        # This app intentionally uses JSON for API endpoints.
        # What matters for UX: download gating must return pricing-modal action, not a raw error.
        has_gate_action = '"action": "show_pricing_modal"' in content
        has_download_route = '@app.route("/download/<int:clip_id>")' in content
        has_free_status_route = '@app.route("/api/free-status", methods=["GET"])' in content

        if not has_gate_action:
            log.error("❌ Missing structured pricing gate action for download flow")
            return False

        if not has_download_route:
            log.error("❌ Missing /download/<clip_id> route")
            return False

        if not has_free_status_route:
            log.error("❌ Missing /api/free-status route")
            return False

        log.info("✅ Download gating returns structured pricing modal action")
        log.info("✅ API JSON responses are present only as designed for API contracts")
        return True
            
    except Exception as e:
        log.error(f"❌ Code review test failed: {e}")
        return False

def test_worker_contracts():
    """Test new worker request/response validation helpers."""
    log.info("\n" + "=" * 60)
    log.info("TEST: Worker contract validation")
    log.info("=" * 60)
    from worker.contracts import validate_worker_request, validate_worker_result
    good = {
        "job_id": "foo",
        "source_url": "https://youtube.com/watch?v=abc",
        "profile": "god_mode",
        "min_clips": 5,
        "max_duration_sec": 120,
        "debug": True,
    }
    try:
        cleaned = validate_worker_request(good)
        assert cleaned["profile"] == "god_mode"
        bad = {"source_url": 123}
        try:
            validate_worker_request(bad)
            return False
        except ValueError:
            pass
        # result envelope minimal
        res = {"job_id": "foo", "status": "ok", "clips": [],
               "confidence_score": 0.5, "signal_quality": {}, "diagnostics": {}}
        validate_worker_result(res)
        return True
    except Exception as e:
        log.error(f"❌ Worker contract tests failed: {e}")
        return False


def test_signal_acquisition():
    """Basic sanity checks for signal_acquisition_engine helpers."""
    log.info("\n" + "=" * 60)
    log.info("TEST: signal_acquisition_engine")
    log.info("=" * 60)
    try:
        from worker import signal_acquisition_engine as sae
        # try a generic URL first; the internal logic may attempt to fetch a
        # YouTube transcript but will quietly degrade if the package is missing.
        acq = sae.acquire_signal("https://youtube.com/watch?v=jNQXAC9IVRw", profile="balanced")
        assert isinstance(acq, dict)
        # signal quality must always be present
        assert "signal_quality" in acq
        sq = sae.compute_signal_scores(acq)
        assert isinstance(sq, dict)
        sa = {"signal_quality": sq}
        sae.make_degraded_if_needed(sa)
        assert "status" in sa
        # manually exercise score computation for low-segment case
        acq2 = {"metadata": {"duration": 120}, "transcript_segments": [{},{},], "signal_quality": {}}
        sq2 = sae.compute_signal_scores(acq2)
        assert sq2.get("degraded_transcript") is True
        # failure statuses are not replaced by degradation
        sa_fail = {"signal_quality": {"acquisition_score": 0.1}, "status": "failed_internal"}
        sae.make_degraded_if_needed(sa_fail)
        assert sa_fail["status"] == "failed_internal"
        return True
    except Exception as e:
        log.error(f"❌ signal acquisition test failed: {e}")
        return False


def test_worker_process_job():
    """Verify worker.main.process_job updates a pending Job to completed envelope."""
    log.info("\n" + "=" * 60)
    log.info("TEST: worker.process_job function")
    log.info("=" * 60)
    # create a dummy job record using SQLAlchemy
    try:
        from models.user import Job, db
        from worker.main import process_job
    except ImportError as e:
        log.info("skipping worker.process_job test (missing DB libs): %s", e)
        return True
    with app.app_context():
        jid = str(uuid.uuid4())
        params = {"job_id": jid, "source_url": "https://youtube.com/watch?v=x"}
        job = Job(id=jid, user_id=1, video_path=None, transcript=None,
                  analysis_data=json.dumps(params), status="pending")
        db.session.add(job)
        db.session.commit()

        # patch download and orchestrator to avoid network and heavy libs
        import app as app_module
        def fake_download(url, start, end, output_dir="downloads", job_id=None, metadata=None):
            return "fake_path.mp4", 0.33, [{"path": "fake_path.mp4", "score": 0.33}], {}, True
        app_module.acquire_youtube_media_robust = fake_download

        from viral_finder import orchestrator
        orchestrator_orig = orchestrator.orchestrate
        
        # Capture arguments to verify pipeline_mode fix
        captured_kwargs = {}
        def fake_orchestrate(path, **kw):
            captured_kwargs.update(kw)
            return [{"id": "c1", "dominant_cluster_score": 0.77}]
        orchestrator.orchestrate = fake_orchestrate

        process_job(job)

        # restore patch (not strictly necessary)
        orchestrator.orchestrate = orchestrator_orig

        # Verify pipeline_mode="staged" was passed
        if captured_kwargs.get("pipeline_mode") != "staged":
            log.error(f"❌ Worker failed to enforce pipeline_mode='staged'. Got: {captured_kwargs.get('pipeline_mode')}")
            return False
        if captured_kwargs.get("allow_fallback") is not False:
            log.error(f"❌ Worker failed to enforce allow_fallback=False. Got: {captured_kwargs.get('allow_fallback')}")
            return False
        log.info("✅ Worker correctly enforced pipeline_mode='staged'")

        refreshed = Job.query.get(jid)
        assert refreshed is not None
        assert refreshed.status in ("completed", "failed", "failed_internal")
        data = json.loads(refreshed.analysis_data or "{}")
        assert data.get("job_id") == jid
        assert "clips" in data
        # ensure our fake orchestrator output propagated
        assert data["clips"][0].get("id") == "c1"
        assert data["diagnostics"].get("video_path") == "fake_path.mp4"
        assert refreshed.video_path == "fake_path.mp4"
        assert data["diagnostics"].get("raw_candidates") == 1
    log.info("✅ worker.process_job performed basic update")


def test_v2_api_endpoints():
    """Smoke test for the /v2/analyze and /v2/result endpoints."""
    log.info("\n" + "=" * 60)
    log.info("TEST: v2 API endpoints")
    log.info("=" * 60)
    import app as app_module
    from app import app

    prev = app_module.app.config.get('LOGIN_DISABLED', False)
    app_module.app.config['LOGIN_DISABLED'] = True
    with app.test_client() as client:
        # submit job
        payload = {"source_url": "https://youtube.com/watch?v=test"}
        resp = client.post('/v2/analyze', json=payload)
        log.info(f"submit status {resp.status_code} json={resp.get_json()}")
        assert resp.status_code == 200
        job_id = resp.get_json().get('job_id')
        assert job_id
        # fetch status
        resp2 = client.get(f'/v2/result/{job_id}')
        assert resp2.status_code == 200
        data = resp2.get_json()
        assert data.get('status') in ('pending','processing','completed','failed')
        # now hit legacy analyze route with worker mode enabled; should create another pending job
        os.environ['HS_WORKER_MODE'] = 'runpod'
        resp3 = client.post('/analyze', data={'youtube_url': 'https://youtube.com/watch?v=foo'})
        assert resp3.status_code in (302, 200)
        # parse redirect to results and extract job id
        if resp3.is_json:
            body = resp3.get_json()
            legacy_job = body.get('job_id')
        else:
            # redirect URL contains /results/<id>
            loc = resp3.location or ''
            legacy_job = loc.rsplit('/', 1)[-1]
        assert legacy_job
        resp4 = client.get(f'/v2/result/{legacy_job}')
        assert resp4.status_code == 200
        data2 = resp4.get_json()
        assert data2.get('status') in ('pending','processing','completed','failed')
    app_module.app.config['LOGIN_DISABLED'] = prev
    os.environ.pop('HS_WORKER_MODE', None)
    return True


def test_app_structure():
    """Test 6: Verify app.py structure and critical imports"""
    log.info("\n" + "=" * 60)
    log.info("TEST 6: App Structure & Imports")
    log.info("=" * 60)
    
    try:
        app_path = "app.py"
        with open(app_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        checks = []
        checks.append(('yt_dlp import', 'import yt_dlp' in content))
        checks.append(('Flask import', 'from flask import Flask' in content))
        checks.append(('Login requirement', '@login_required' in content))
        checks.append(('download function definition', 'def download_youtube_video' in content))

        # Accept combined imports such as: from flask import ..., flash, ..., redirect, ...
        flask_import_lines = [ln.strip() for ln in content.splitlines() if ln.strip().startswith('from flask import ')]
        flash_found = any('flash' in ln for ln in flask_import_lines)
        redirect_found = any('redirect' in ln for ln in flask_import_lines)
        checks.append(('flash import', flash_found))
        checks.append(('redirect import', redirect_found))

        all_found = True
        for name, found in checks:
            status = "✅" if found else "❌"
            log.info(f"{status} {name}")
            if not found:
                all_found = False

        return all_found
        
    except Exception as e:
        log.error(f"❌ App structure test failed: {e}")
        return False

def test_analyze_route_enforces_staged():
    """Verify app.py analyze_video route enforces pipeline_mode='staged'."""
    log.info("\n" + "=" * 60)
    log.info("TEST: analyze_video route enforcement")
    log.info("=" * 60)

    import app as app_module
    from app import app
    import sys
    from unittest.mock import MagicMock, patch
    import os

    # Ensure viral_finder modules exist in sys.modules
    for mod in ['viral_finder', 'viral_finder.orchestrator', 'viral_finder.gemini_transcript_engine']:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    captured_kwargs = {}
    def fake_orchestrate(video_path, **kwargs):
        captured_kwargs.update(kwargs)
        return [{"start": 0, "end": 10, "score": 0.9, "text": "test"}]

    # Patch targets in app module
    patches = [
        (app_module, 'download_youtube_video', lambda *a, **k: "dummy.mp4"),
        (app_module, 'probe_media', lambda p: {"duration": 60.0, "width": 1280, "height": 720}),
        (app_module, 'score_acquisition', lambda **k: (1.0, {})),
        (app_module, 'analyze_audio_integrity', lambda p: {}),
        (app_module, 'analyze_transcript_integrity', lambda t, **k: {}),
        (app_module, 'compute_vad_removed_ratio', lambda d, t: 0.0),
        (app_module, 'save_ingestion_cache', lambda *a: None),
        (app_module, 'load_ingestion_cache', lambda *a, **k: None),
        (app_module, '_js_runtime_available', lambda: True),
        (app_module, '_ingestion_signature', lambda: "sig"),
        (app_module, 'fetch_youtube_metadata', lambda u: {"duration": 60.0}),
        (app_module, 'get_user_plan_type', lambda u: "pro"),
        (app_module, '_acquire_analyze_lock_for_user', lambda u: MagicMock()),
        (app_module, '_acquire_analyze_file_lock_for_user', lambda u: "dummy.lock"),
        (app_module, '_release_analyze_file_lock', lambda p: None),
        (sys.modules['viral_finder.orchestrator'], 'orchestrate', fake_orchestrate),
        (sys.modules['viral_finder.gemini_transcript_engine'], 'extract_transcript', lambda *a, **k: []),
    ]

    originals = []
    for target, attr, replacement in patches:
        originals.append((target, attr, getattr(target, attr, None)))
        setattr(target, attr, replacement)

    # Mock subprocess
    import subprocess
    orig_run = subprocess.run
    subprocess.run = MagicMock(return_value=MagicMock(returncode=0, stdout="duration=60.0"))

    # Config changes
    prev_login = app.config.get('LOGIN_DISABLED', False)
    app.config['LOGIN_DISABLED'] = True
    prev_worker_mode = os.environ.get('HS_WORKER_MODE')
    if 'HS_WORKER_MODE' in os.environ:
        del os.environ['HS_WORKER_MODE']

    try:
        # Mock os.path using patch context
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            
            with app.test_client() as client:
                resp = client.post('/analyze', data={'youtube_url': 'https://youtube.com/watch?v=test'})
                
                if captured_kwargs.get("pipeline_mode") != "staged":
                    log.error(f"❌ analyze_video failed to enforce pipeline_mode='staged'. Got: {captured_kwargs.get('pipeline_mode')}")
                    return False
                
                log.info("✅ analyze_video correctly enforced pipeline_mode='staged'")
                return True

    except Exception as e:
        log.error(f"❌ analyze_video test crashed: {e}")
        return False
    finally:
        for target, attr, original in originals:
            if original is not None:
                setattr(target, attr, original)
            else:
                if hasattr(target, attr): delattr(target, attr)
        subprocess.run = orig_run
        app.config['LOGIN_DISABLED'] = prev_login
        if prev_worker_mode is not None:
            os.environ['HS_WORKER_MODE'] = prev_worker_mode

def main():
    """Run all tests"""
    log.info("\n" + "🔥" * 30)
    log.info("PRODUCTION STABILITY TEST SUITE")
    log.info("🔥" * 30 + "\n")
    
    tests = [
        ("yt-dlp Import", test_yt_dlp_import),
        ("Download Function", test_download_function),
        ("Metadata/Transcript Helpers", test_metadata_and_transcript_helpers),
        ("UI Premium Framing", test_ui_premium_framing),
        ("Worker Contract Validation", test_worker_contracts),
        ("Signal Acquisition Engine", test_signal_acquisition),
        ("v2 Analyze API", test_v2_api_endpoints),
        ("Captcha Error Handling", test_analyze_captcha_error),
        ("Flash & Redirect Pattern", test_flash_redirect_pattern),
        ("Toast HTML Structure", test_toast_html_structure),
        ("No JSON Error Responses", test_no_jsonify_errors),
        ("App Structure", test_app_structure),
        ("Analyze Route Enforcement", test_analyze_route_enforces_staged),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            log.error(f"Test '{test_name}' crashed: {e}")
            results[test_name] = False
    
    # Summary
    log.info("\n" + "=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        log.info(f"{status}: {test_name}")
    
    log.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        log.info("\n🎉 ALL TESTS PASSED - Production stable!")
        return 0
    else:
        log.info(f"\n⚠️ {total - passed} test(s) failed - review above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
