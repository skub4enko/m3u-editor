from pathlib import Path

p = Path('radio_m3u.py')
text = p.read_text(encoding='utf-8')

old = '''        url = _normalize_url(url_in)
        if not args.skip_check:
            print("Checking...", end=" ")
            start = time.time()
            res = check_stream(url, timeout=args.timeout, user_agent=args.user_agent)'''

new = '''        url_candidates = _candidate_urls(url_in)
        url = url_candidates[0] if url_candidates else ""
        if not args.skip_check:
            print("Checking...", end=" ")
            start = time.time()
            res = check_stream(url_in, timeout=args.timeout, user_agent=args.user_agent)'''

if old not in text:
    raise SystemExit('Pattern not found for main() URL block')

text = text.replace(old, new, 1)
text = text.replace('{"y", "yes", "ä", "äà"}', '{"y", "yes", "д", "да"}')
text = text.replace('# If they said y/äà to try another url, continue loop.', '# If they said y/да to try another url, continue loop.')

p.write_text(text, encoding='utf-8', newline='\n')
print('OK')
