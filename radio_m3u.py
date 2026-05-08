#!/usr/bin/env python3
"""Interactive M3U generator for radio/streams.

Flow (loop):
  1) Choose output file (new or continue)
  2) Ask stream URL
  3) Validate (best-effort: checks it responds like audio/HLS)
  4) Ask station name
  5) Ask logo URL (optional)
  6) Append to output M3U

Produces entries like:
  #EXTINF:-1 tvg-logo="...",Station Name
  https://example/stream

Notes:
  - "plays or not" can't be guaranteed without decoding audio, so validation is heuristic.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


M3U_HEADER = "#EXTM3U"

def _app_state_dir() -> Path:
    # When packaged with PyInstaller, __file__ points inside the temporary bundle.
    # Store small state next to the executable instead.
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            return Path.cwd()
    return Path(__file__).resolve().parent


LAST_OUT_FILE = _app_state_dir() / ".radio_m3u_last_out.txt"


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str
    final_url: str
    content_type: str
    status: Optional[int]


def _normalize_url(url: str) -> str:
    return url.strip()


def _candidate_urls(url: str) -> list[str]:
    url = url.strip()
    if not url:
        return []
    if "://" in url:
        return [url]
    # Prefer https, fall back to http.
    return [f"https://{url}", f"http://{url}"]


def _is_probably_hls(content_type: str, url: str) -> bool:
    ct = (content_type or "").lower()
    if "mpegurl" in ct or "m3u8" in ct:
        return True
    return url.lower().split("?", 1)[0].endswith(".m3u8")


def _is_probably_audio(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return ct.startswith("audio/") or any(
        x in ct
        for x in [
            "application/ogg",
            "application/octet-stream",  # many streams lie
            "video/mp2t",  # HLS segments
        ]
    )


def _request(url: str, method: str, timeout: float, user_agent: str) -> urllib.response.addinfourl:
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Icy-MetaData": "1",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout)  # nosec - user provided URL by design


def _read_some(resp: urllib.response.addinfourl, limit: int) -> bytes:
    try:
        return resp.read(limit)
    except Exception:
        return b""


def _check_one_stream(one_url: str, timeout: float, user_agent: str) -> CheckResult:
    parsed = urllib.parse.urlparse(one_url)
    if parsed.scheme not in {"http", "https"}:
        return CheckResult(False, f"unsupported scheme: {parsed.scheme}", one_url, "", None)
    if not parsed.netloc:
        return CheckResult(False, "missing host", one_url, "", None)

    last_err: Optional[str] = None

    # Try HEAD first (fast), then fall back to GET for stronger validation.
    for method in ("HEAD", "GET"):
        try:
            with _request(one_url, method=method, timeout=timeout, user_agent=user_agent) as resp:
                final_url = getattr(resp, "geturl", lambda: one_url)()
                status = getattr(resp, "status", None)
                headers = getattr(resp, "headers", {})
                content_type = headers.get("Content-Type", "")

                body = b""
                if method == "GET":
                    body = _read_some(resp, 2048)

                if status is not None and status >= 400:
                    return CheckResult(False, f"http {status}", final_url, content_type, status)

                if _is_probably_hls(content_type, final_url):
                    if method != "GET":
                        continue
                    text = body.decode("utf-8", errors="ignore")
                    if "#EXTM3U" in text or re.search(r"\n#EXTINF:|\n#EXT-X-", text):
                        return CheckResult(True, "looks like HLS playlist", final_url, content_type, status)
                    return CheckResult(False, "HLS content-type but playlist not recognized", final_url, content_type, status)

                if _is_probably_audio(content_type):
                    return CheckResult(True, "responds like audio", final_url, content_type, status)

                if method == "HEAD":
                    continue

                if body:
                    return CheckResult(True, "responds (unknown content-type)", final_url, content_type, status)

                return CheckResult(False, "unrecognized content-type", final_url, content_type, status)

        except urllib.error.HTTPError as e:
            last_err = f"http error: {getattr(e, 'code', '')}".strip()
        except urllib.error.URLError as e:
            last_err = f"url error: {getattr(e, 'reason', e)}"
        except TimeoutError:
            last_err = "timeout"
        except Exception as e:
            last_err = f"error: {e.__class__.__name__}: {e}"

    return CheckResult(False, last_err or "request failed", one_url, "", None)


def check_stream(url: str, timeout: float = 8.0, user_agent: str = "radio_m3u/1.0") -> CheckResult:
    """Validate a stream URL.

    If the user pasted an URL without scheme, tries https:// first and then http://.
    """

    raw = _normalize_url(url)
    candidates = _candidate_urls(raw)
    if not candidates:
        return CheckResult(False, "empty url", "", "", None)

    if "://" in raw:
        return _check_one_stream(candidates[0], timeout=timeout, user_agent=user_agent)

    last: Optional[CheckResult] = None
    for one in candidates:
        res = _check_one_stream(one, timeout=timeout, user_agent=user_agent)
        if res.ok:
            return res
        last = res

    assert last is not None
    return CheckResult(False, f"both https/http failed; last: {last.reason}", last.final_url, last.content_type, last.status)


def _m3u_escape_attr(value: str) -> str:
    return value.replace('"', "'").strip()


def append_station(out_path: str, name: str, stream_url: str, logo_url: str = "") -> None:
    name = name.strip()
    stream_url = stream_url.strip()
    logo_url = logo_url.strip()

    if not name:
        raise ValueError("name is empty")
    if not stream_url:
        raise ValueError("stream_url is empty")

    extinf = "#EXTINF:-1"
    if logo_url:
        extinf += f" tvg-logo=\"{_m3u_escape_attr(logo_url)}\""
    extinf += f",{name}"

    try:
        with open(out_path, "r", encoding="utf-8") as f:
            existing = f.read(2048)
    except FileNotFoundError:
        existing = ""

    mode = "a" if existing else "w"
    with open(out_path, mode, encoding="utf-8", newline="\n") as f:
        if not existing:
            f.write(M3U_HEADER + "\n")
        if existing and not existing.endswith(("\n", "\r")):
            f.write("\n")
        f.write(extinf + "\n")
        f.write(stream_url + "\n")


def _prompt(label: str, allow_empty: bool = False) -> str:
    while True:
        try:
            val = input(label).strip()
        except EOFError:
            return ""
        if val or allow_empty:
            return val


def _is_yes(s: str) -> bool:
    s = s.strip().lower()
    return s in {"y", "yes", "д", "да"}


def _load_last_out() -> str:
    try:
        return LAST_OUT_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _save_last_out(path: str) -> None:
    try:
        LAST_OUT_FILE.write_text(path.strip() + "\n", encoding="utf-8", newline="\n")
    except Exception:
        # Non-fatal.
        pass


def _choose_output(default_out: str) -> str:
    last_out = _load_last_out()
    suggested = last_out or default_out

    print("Выбор файла плейлиста:")
    print(f"  1) Сделать новый файл")
    print(f"  2) Продолжить работу с последним ({suggested})")

    while True:
        choice = _prompt("Выбери 1 или 2: ", allow_empty=False)
        if choice in {"1", "2"}:
            break
        print("Нужно ввести 1 или 2.")

    if choice == "2":
        out = suggested
        _save_last_out(str(Path(out).resolve()))
        return out

    name = _prompt("Название нового плейлиста (например rock): ", allow_empty=False)
    name = name.strip().strip('"').strip("'")
    if not name.lower().endswith(".m3u"):
        name += ".m3u"

    out = str((Path.cwd() / name).resolve())
    _save_last_out(out)
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Interactive radio M3U builder")
    p.add_argument("--out", default="rock.m3u", help="Output .m3u path (default: rock.m3u)")
    p.add_argument("--timeout", type=float, default=8.0, help="Seconds to wait for URL check")
    p.add_argument("--skip-check", action="store_true", help="Do not validate stream URLs")
    p.add_argument("--user-agent", default="radio_m3u/1.0", help="User-Agent for URL checks")
    args = p.parse_args(argv)

    out_path = _choose_output(args.out)

    print(f"Output: {out_path}")
    print("Enter empty URL to finish.")

    added = 0
    while True:
        url_in = _prompt("Stream URL: ", allow_empty=True)
        if not url_in:
            break

        url_candidates = _candidate_urls(url_in)
        url = url_candidates[0] if url_candidates else ""

        if not args.skip_check:
            print("Checking...", end=" ")
            start = time.time()
            res = check_stream(url_in, timeout=args.timeout, user_agent=args.user_agent)
            elapsed = time.time() - start

            if not res.ok:
                print(f"FAIL ({res.reason}, {elapsed:.1f}s)")
                if _is_yes(_prompt("Try another URL? (y/n): ")):
                    continue
                if not _is_yes(_prompt("Add anyway? (y/n): ")):
                    continue
                # keep `url` as-is (https://... if no scheme)
            else:
                ct = (res.content_type or "").split(";", 1)[0]
                status = f"{res.status}" if res.status is not None else "?"
                print(f"OK ({res.reason}, HTTP {status}, {ct or 'no-ct'}, {elapsed:.1f}s)")
                url = res.final_url or url

        name = _prompt("Station name: ")
        logo = _prompt("Logo URL (optional): ", allow_empty=True)

        try:
            append_station(out_path, name=name, stream_url=url, logo_url=logo)
        except Exception as e:
            print(f"Could not write entry: {e}", file=sys.stderr)
            continue

        added += 1
        print(f"Added. Total: {added}\n")

    print(f"Done. Added: {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
