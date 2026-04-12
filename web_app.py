import json
import os
import re
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, stream_with_context
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
UPSTREAM_TIMEOUT_SECONDS = 900
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object("settings.Config")
    app.secret_key = app.config["SECRET_KEY"]
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    def _public_origin() -> str:
        configured = (os.getenv("FRONTEND_URL") or app.config.get("FRONTEND_URL") or "").strip().rstrip("/")
        if configured:
            return configured
        return request.host_url.rstrip("/")

    def _upstream_origin() -> str:
        return (
            os.getenv("PROCESSING_BACKEND_URL")
            or os.getenv("BACKEND_URL")
            or os.getenv("EXTERNAL_BASE_URL")
            or ""
        ).strip().rstrip("/")

    app.config["FRONTEND_URL"] = (os.getenv("FRONTEND_URL") or app.config.get("FRONTEND_URL") or "").strip().rstrip("/")
    app.config["BACKEND_URL"] = app.config["FRONTEND_URL"]
    app.config["EXTERNAL_BASE_URL"] = app.config["FRONTEND_URL"]
    app.config["PROCESSING_BACKEND_URL"] = _upstream_origin()

    def _normalize_public_url(value: str, public_origin: str, upstream_origin: str) -> str:
        if not value:
            return value
        text = str(value)
        if upstream_origin and text.startswith(upstream_origin):
            return f"{public_origin}{text[len(upstream_origin):]}"
        if text.startswith("/") and public_origin:
            return f"{public_origin}{text}"
        return text

    def _rewrite_json_payload(payload, public_origin: str, upstream_origin: str):
        if isinstance(payload, dict):
            rewritten = {}
            for key, value in payload.items():
                new_value = _rewrite_json_payload(value, public_origin, upstream_origin)
                if key in {"redirect", "redirect_url", "results_url", "absolute_results_url", "login_url"} and isinstance(new_value, str):
                    new_value = _normalize_public_url(new_value, public_origin, upstream_origin)
                rewritten[key] = new_value
            return rewritten
        if isinstance(payload, list):
            return [_rewrite_json_payload(item, public_origin, upstream_origin) for item in payload]
        if isinstance(payload, str) and upstream_origin and upstream_origin in payload:
            return payload.replace(upstream_origin, public_origin)
        return payload

    def _rewrite_text_payload(text: str, public_origin: str, upstream_origin: str) -> str:
        rewritten = text
        if upstream_origin:
            rewritten = rewritten.replace(upstream_origin, public_origin)
            rewritten = rewritten.replace(
                quote(upstream_origin, safe=""),
                quote(public_origin, safe=""),
            )
        return rewritten

    def _prepare_upstream_headers():
        headers = {}
        for key, value in request.headers.items():
            lowered = key.lower()
            if lowered in HOP_BY_HOP_HEADERS or lowered in {"host", "content-length"}:
                continue
            headers[key] = value

        headers["X-Forwarded-Host"] = request.host
        headers["X-Forwarded-Proto"] = request.headers.get("X-Forwarded-Proto", request.scheme)
        headers["X-Forwarded-For"] = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        return headers

    def _copy_response_headers(proxy_response: Response, upstream_response, rewrite_body: bool):
        for key, value in upstream_response.headers.items():
            lowered = key.lower()
            if lowered in HOP_BY_HOP_HEADERS or lowered == "set-cookie":
                continue
            if rewrite_body and lowered in {"content-length", "content-encoding"}:
                continue
            if lowered == "location":
                public_origin = _public_origin()
                upstream_origin = _upstream_origin()
                if isinstance(value, str):
                    value = _rewrite_text_payload(value, public_origin, upstream_origin)
                    value = _normalize_public_url(value, public_origin, upstream_origin)
            proxy_response.headers[key] = value

        raw_headers = getattr(upstream_response.raw, "headers", None)
        getlist = getattr(raw_headers, "getlist", None)
        if getlist:
            for cookie_header in getlist("Set-Cookie"):
                if cookie_header:
                    proxy_response.headers.add("Set-Cookie", cookie_header)

    def _proxy_to_upstream(path: str):
        upstream_origin = _upstream_origin()
        if not upstream_origin:
            return {"ok": False, "error": "PROCESSING_BACKEND_URL is not configured."}, 503

        upstream_url = f"{upstream_origin}{path}"
        upstream_response = requests.request(
            method=request.method,
            url=upstream_url,
            params=request.args,
            data=request.get_data(),
            headers=_prepare_upstream_headers(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        )

        public_origin = _public_origin()
        content_type = (upstream_response.headers.get("Content-Type") or "").lower()
        rewrite_body = False

        if "application/json" in content_type:
            rewrite_body = True
            payload = upstream_response.json()
            rewritten_payload = _rewrite_json_payload(payload, public_origin, upstream_origin)
            response = app.response_class(
                response=json.dumps(rewritten_payload),
                status=upstream_response.status_code,
                mimetype="application/json",
            )
        elif content_type.startswith("text/") or "javascript" in content_type or "xml" in content_type:
            rewrite_body = True
            upstream_response.encoding = upstream_response.encoding or "utf-8"
            rewritten_text = _rewrite_text_payload(upstream_response.text, public_origin, upstream_origin)
            response = Response(
                rewritten_text,
                status=upstream_response.status_code,
                content_type=upstream_response.headers.get("Content-Type"),
            )
        else:
            response = Response(
                stream_with_context(upstream_response.iter_content(chunk_size=65536)),
                status=upstream_response.status_code,
                content_type=upstream_response.headers.get("Content-Type"),
            )

        _copy_response_headers(response, upstream_response, rewrite_body=rewrite_body)
        return response

    @app.context_processor
    def inject_backend_url():
        return {
            "BACKEND_URL": "",
            "FRONTEND_URL": _public_origin(),
        }

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/static/outputs/<path:filename>", methods=ALL_METHODS)
    def proxy_static_outputs(filename):
        return _proxy_to_upstream(f"/static/outputs/{filename}")

    @app.route("/output/<path:filename>", methods=ALL_METHODS)
    def proxy_output(filename):
        return _proxy_to_upstream(f"/output/{filename}")

    @app.route("/<path:path>", methods=ALL_METHODS)
    def proxy_all(path):
        return _proxy_to_upstream(f"/{path}")

    return app


app = create_app()
