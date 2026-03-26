import importlib


app = importlib.import_module("app")


def test_download_youtube_video_falls_back_to_local_when_runpod_disabled(monkeypatch):
    monkeypatch.delenv("HS_RUNPOD_DOWNLOAD", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    monkeypatch.setattr(app, "IS_RENDER_RUNTIME", False, raising=False)

    calls = {}

    def _fake_local(url, output_dir="downloads", job_id=None):
        calls["url"] = url
        calls["output_dir"] = output_dir
        calls["job_id"] = job_id
        return "downloads/local.mp4"

    monkeypatch.setattr(app, "download_with_fallback", _fake_local)

    out = app.download_youtube_video(
        "https://youtube.com/watch?v=abc",
        output_dir="downloads",
        job_id="job-local",
    )

    assert out == "downloads/local.mp4"
    assert calls == {
        "url": "https://youtube.com/watch?v=abc",
        "output_dir": "downloads",
        "job_id": "job-local",
    }


def test_download_youtube_video_returns_none_on_render_when_runpod_disabled(monkeypatch):
    monkeypatch.delenv("HS_RUNPOD_DOWNLOAD", raising=False)
    monkeypatch.setattr(app, "IS_RENDER_RUNTIME", True, raising=False)

    monkeypatch.setattr(
        app,
        "download_with_fallback",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local fallback should not run on Render")),
    )

    out = app.download_youtube_video(
        "https://youtube.com/watch?v=abc",
        output_dir="downloads",
        job_id="job-render",
    )

    assert out is None
