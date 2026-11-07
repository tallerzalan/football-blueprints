"""Fill extra_matches.csv with Barça's Supercopa and Copa del Rey matches from Wikipedia.

The free match sources the app reads live (football-data.co.uk, openfootball) do not cover these
competitions for every season, so this script takes them from the English Wikipedia season pages
("2025–26 FC Barcelona season" etc.), whose match boxes link to LaLiga's official match reports.

    python barca-flick/update_from_wikipedia.py              # fetch pages and rewrite the Wikipedia rows
    python barca-flick/update_from_wikipedia.py --from-dir D # use saved API responses (w_<season>.json)

Rows whose `source` does not start with "Wikipedia" (your own additions) are kept as they are.
Matches without a score yet (scheduled) are skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

HERE = Path(__file__).parent
CSV = HERE / "extra_matches.csv"
SEASONS = ["2024–25", "2025–26", "2026–27"]  # en dash, as in the page titles
COMPETITIONS = ("Supercopa de España", "Copa del Rey")
API = "https://en.wikipedia.org/w/api.php?action=parse&page={page}&prop=wikitext|revid&format=json&formatversion=2&redirects=1"
UA = "BarcaFlickDashboard/1.0 (+https://github.com/tallerzalan/football-blueprints)"
COLUMNS = ["date", "competition", "round", "opponent", "venue", "gf", "ga", "note",
           "stadium", "attendance", "referee", "report", "source"]


def fetch(season: str) -> dict:
    url = API.format(page=quote(f"{season}_FC_Barcelona_season"))
    for attempt in range(4):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code == 429:  # Wikimedia rate limit: wait as asked
            time.sleep(int(r.headers.get("retry-after", 30)) + 5)
            continue
        r.raise_for_status()
        return r.json()["parse"]
    raise RuntimeError(f"Wikipedia kept rate-limiting {url}")


def clean(v: str) -> str:
    v = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"\{\{fbaicon\|[^}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    return re.sub(r"\s+", " ", v).strip()


def match_boxes(wikitext: str):
    """Yield (section titles, fields) for every {{Football box collapsible}}."""
    sec: list[str] = []
    for m in re.finditer(r"^(={2,5})\s*(.*?)\s*\1\s*$|\{\{\s*Football box collapsible", wikitext, re.M):
        if m.group(1):
            sec = sec[: len(m.group(1)) - 2] + [m.group(2)]
            continue
        i, depth = m.start(), 0
        while i < len(wikitext):
            if wikitext.startswith("{{", i):
                depth, i = depth + 1, i + 2
            elif wikitext.startswith("}}", i):
                depth, i = depth - 1, i + 2
                if depth == 0:
                    break
            else:
                i += 1
        fields, key = {}, None
        for line in wikitext[m.end(): i - 2].splitlines():
            km = re.match(r"^\s*\|\s*([a-z0-9_ ]+?)\s*=\s*(.*)$", line)
            if km:
                key = km.group(1).strip()
                fields[key] = km.group(2)
            elif key:
                fields[key] += "\n" + line
        yield list(sec), fields


def rows_from_page(page: dict) -> list[dict]:
    out = []
    for sec, f in match_boxes(page["wikitext"]):
        comp = next((c for c in COMPETITIONS if any(s.startswith(c) for s in sec)), None)
        if comp is None:
            continue
        sm = re.match(r"^\s*(\d+)\s*[–-]\s*(\d+)", f.get("score", ""))
        if not sm:
            continue  # not played yet
        t1, t2 = clean(f.get("team1", "")), clean(f.get("team2", ""))
        if "Barcelona" not in (t1, t2):
            continue
        home = t1 == "Barcelona"
        s1, s2 = int(sm[1]), int(sm[2])
        rnd = clean(f.get("round", "")).replace("<br>", " ").replace("<br />", " ")
        leg = re.search(r"(First|Second) leg", rnd)
        stage = re.sub(r"\s*(First|Second) leg", "", rnd).strip()
        notes = []
        if leg:
            notes.append(f"{leg[1].lower()} leg")
        if f.get("aet", "").strip():
            notes.append("a.e.t.")
        pens = re.match(r"^\s*(\d+)\s*[–-]\s*(\d+)", f.get("penaltyscore", ""))
        if pens:
            pf, pa = (int(pens[1]), int(pens[2])) if home else (int(pens[2]), int(pens[1]))
            notes.append(f"{'won' if pf > pa else 'lost'} {pf}-{pa} on pens")
        # Supercopa is played at a neutral venue (Saudi Arabia in these seasons); so is the Copa final
        neutral = comp == "Supercopa de España" or stage == "Final"
        att = re.sub(r"[^\d]", "", clean(f.get("attendance", "")))
        out.append({
            "date": datetime.strptime(clean(f["date"]), "%d %B %Y").date().isoformat(),
            "competition": comp, "round": stage, "opponent": t2 if home else t1,
            "venue": "Neutral" if neutral else ("Home" if home else "Away"),
            "gf": s1 if home else s2, "ga": s2 if home else s1, "note": ", ".join(notes),
            "stadium": clean(f.get("stadium", "")), "attendance": int(att) if att else None,
            "referee": clean(f.get("referee", "")), "report": f.get("report", "").strip(),
            "source": f"Wikipedia: {page['title']} (rev {page['revid']})",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", type=Path, help="folder with saved API responses w_<season>.json")
    args = ap.parse_args()
    rows = []
    for s in SEASONS:
        if args.from_dir:
            page = json.loads((args.from_dir / f"w_{quote(s)}.json").read_text(encoding="utf-8"))["parse"]
        else:
            page = fetch(s)
            time.sleep(5)
        found = rows_from_page(page)
        print(f"{page['title']} rev {page['revid']}: {len(found)} played Supercopa/Copa matches")
        rows += found
    old = pd.read_csv(CSV) if CSV.exists() else pd.DataFrame(columns=COLUMNS)
    if "source" not in old:
        old["source"] = ""
    keep = old[~old["source"].fillna("").str.startswith("Wikipedia")]
    new = pd.concat([keep, pd.DataFrame(rows)], ignore_index=True).reindex(columns=COLUMNS)
    new.sort_values("date").to_csv(CSV, index=False)
    print(f"wrote {len(new)} rows to {CSV.name} ({len(keep)} of your own kept)")


if __name__ == "__main__":
    main()
