import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CHECKS = (
    ("/", 200, "app_html"),
    ("/health", 200, "ok"),
    ("/auth/login", 200, "login_page"),
    ("/static/style.css", 200, "static_asset"),
)


def fetch(base_url: str, path: str):
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"User-Agent": "hotshort-smoke-check"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except URLError as exc:
        raise RuntimeError(f"{path} failed: {exc}") from exc


def validate(path: str, status: int, body: str, expected_status, label: str):
    if isinstance(expected_status, (tuple, list, set)):
        if status not in expected_status:
            raise AssertionError(f"{path} expected HTTP {expected_status}, got {status}")
    elif expected_status is not None and status != expected_status:
        raise AssertionError(f"{path} expected HTTP {expected_status}, got {status}")
    if "NOT_FOUND" in body and "The page could not be found" in body:
        raise AssertionError(f"{path} returned Vercel platform NOT_FOUND")
    if label == "ok" and body.strip() != "ok":
        raise AssertionError(f"{path} expected body 'ok', got {body.strip()!r}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/vercel_smoke_check.py <base-url>")

    base_url = sys.argv[1]
    for path, expected_status, label in CHECKS:
        status, body = fetch(base_url, path)
        validate(path, status, body, expected_status, label)
        print(f"PASS {path} -> HTTP {status}")


if __name__ == "__main__":
    main()
