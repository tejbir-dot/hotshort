import importlib

import requests


app = importlib.import_module("app")


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_process_video_hybrid_prefers_local_worker(monkeypatch):
    monkeypatch.setenv("LOCAL_WORKER_URL", "https://local-worker.test/run")
    monkeypatch.setattr(app, "_local_worker_is_alive", lambda *args, **kwargs: True)

    def _unexpected_runpod(*args, **kwargs):
        raise AssertionError("RunPod should not be used when local worker succeeds")

    def _fake_post(url, json, timeout):
        assert url == "https://local-worker.test/run"
        assert json["input"]["task"] == "orchestrate"
        assert json["input"]["youtube_url"] == "https://youtube.com/watch?v=abc"
        assert timeout == 123
        return _Response(payload={"output": {"status": "ok", "clips": []}})

    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setattr(app, "_orchestrate_via_runpod", _unexpected_runpod)

    out = app.process_video_hybrid("https://youtube.com/watch?v=abc", job_id="job-1", timeout=123)
    assert out == {"status": "ok", "clips": []}


def test_process_video_hybrid_uses_local_gpu_when_worker_unreachable(monkeypatch):
    monkeypatch.setenv("LOCAL_WORKER_URL", "https://local-worker.test/run")
    monkeypatch.setattr(app, "_local_worker_is_alive", lambda *args, **kwargs: False)
    monkeypatch.setattr(app, "_local_gpu_available", lambda: True)

    monkeypatch.setattr(
        app,
        "_orchestrate_via_local_gpu",
        lambda youtube_url, job_id, timeout: {
            "status": "local_gpu",
            "youtube_url": youtube_url,
            "job_id": job_id,
            "timeout": timeout,
        },
    )

    def _unexpected_runpod(*args, **kwargs):
        raise AssertionError("RunPod should not be used when local GPU is available")

    monkeypatch.setattr(app, "_orchestrate_via_runpod", _unexpected_runpod)

    out = app.process_video_hybrid("https://youtube.com/watch?v=abc", job_id="job-2", timeout=456)
    assert out == {
        "status": "local_gpu",
        "youtube_url": "https://youtube.com/watch?v=abc",
        "job_id": "job-2",
        "timeout": 456,
    }


def test_process_video_hybrid_falls_back_to_runpod_when_worker_and_gpu_unavailable(monkeypatch):
    monkeypatch.setenv("LOCAL_WORKER_URL", "https://local-worker.test/run")
    monkeypatch.setattr(app, "_local_worker_is_alive", lambda *args, **kwargs: False)
    monkeypatch.setattr(app, "_local_gpu_available", lambda: False)
    monkeypatch.setattr(
        app,
        "_orchestrate_via_runpod",
        lambda youtube_url, job_id, timeout: {
            "status": "runpod",
            "youtube_url": youtube_url,
            "job_id": job_id,
            "timeout": timeout,
        },
    )

    out = app.process_video_hybrid("https://youtube.com/watch?v=abc", job_id="job-3", timeout=456)
    assert out == {
        "status": "runpod",
        "youtube_url": "https://youtube.com/watch?v=abc",
        "job_id": "job-3",
        "timeout": 456,
    }
