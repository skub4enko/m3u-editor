from pathlib import Path

p = Path("radio_m3u.py")
text = p.read_text(encoding="utf-8")

norm_start = text.index("def _normalize_url")
norm_end = text.index("\n\n\ndef _is_probably_hls")
new_norm = """def _normalize_url(url: str) -> str:
    return url.strip()


def _candidate_urls(url: str) -> list[str]:
    url = url.strip()
    if not url:
        return []
    if "://" in url:
        return [url]
    # Prefer https, fall back to http.
    return [f"https://{url}", f"http://{url}"]
"""
text = text[:norm_start] + new_norm + text[norm_end + 1 :]

cs_start = text.index("def check_stream")
cs_end = text.index("\n\n\ndef _m3u_escape_attr")
new_cs = '''def check_stream(url: str, timeout: float = 8.0, user_agent: str = "radio_m3u/1.0") -> CheckResult:
    """Best-effort 'plays or not' check.

    Notes:
      - We can't truly guarantee playback without a media decoder.
      - We do a HEAD/GET and inspect status, content-type, and (for HLS) basic playlist structure.
    """

    raw = url.strip()
    candidates = _candidate_urls(raw)
    if not candidates:
        return CheckResult(False, "empty url", "", "", None)

    def _check_one(one_url: str) -> CheckResult:
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

                    # If HEAD didn't give us enough signal, try GET.
                    if method == "HEAD":
                        continue

                    # If CT is empty/unknown but we got bytes, still treat as maybe-ok.
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

    # If user already provided a scheme, don't auto-fallback.
    if "://" in raw:
        return _check_one(candidates[0])

    last: Optional[CheckResult] = None
    for one in candidates:
        res = _check_one(one)
        if res.ok:
            return res
        last = res

    assert last is not None
    return CheckResult(False, f"both https/http failed; last: {last.reason}", last.final_url, last.content_type, last.status)
'''
text = text[:cs_start] + new_cs + text[cs_end + 1 :]

p.write_text(text, encoding="utf-8", newline="\n")
print("OK")
