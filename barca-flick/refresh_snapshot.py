"""Refresh the bundled fallback copies in data/ (run from anywhere: python barca-flick/refresh_snapshot.py)."""
import requests

import sources as S

S.SNAP_DIR.mkdir(exist_ok=True)
for url in S.all_source_urls():
    r = requests.get(url, timeout=60, headers={"User-Agent": S.UA})
    if r.status_code == 404:
        print("404 (not published)", url)
        continue
    r.raise_for_status()
    r.encoding = "utf-8"
    S.snap_path(url).write_text(r.text, encoding="utf-8")
    print("saved", S.snap_path(url).name, len(r.text))
