"""Build the possession-flow grids for the "Possession flow" tab from StatsBomb open data.

For one Barça season per coach (La Liga, the matches StatsBomb has released), take Barça's own passes
and carries while Barça are in possession, leave out corners and kick-offs, and accumulate on a
60 x 40 grid (2 x 2 StatsBomb units per cell, 120 x 80 pitch, Barça attacking left to right):

  * ball travel per cell and direction (16 compass bins): every pass/carry is walked along its
    line in small steps, so a long pass adds a little travel to every cell it crosses instead of a
    lot to the cell it started in;
  * travel-weighted ball speed per cell and direction (distance / event duration).

Totals are divided by the number of matches, so seasons with different match counts compare.

    python barca-flick/flow/prepare_flow.py [--cache DIR]

Downloads are cached as compact per-match extracts (only the fields used), so reruns are quick.
Data: StatsBomb open data (https://github.com/statsbomb/open-data) - credit StatsBomb when publishing.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import csv
import gzip
import json
import math
from pathlib import Path

import numpy as np
import requests

RAW = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
TEAM = "Barcelona"
LA_LIGA = 11
GROUPS = [  # key, label, season_id, manager filter (None = every Barça match in that season)
    ("rijkaard_0708", "Frank Rijkaard · 2007/08", 40, "Rijkaard"),
    ("guardiola_1011", "Pep Guardiola · 2010/11", 22, "Guardiola"),
    ("vilanova_1213", "Tito Vilanova · 2012/13", 24, None),
    ("martino_1314", "Gerardo Martino · 2013/14", 25, "Martino"),
    ("enrique_1415", "Luis Enrique · 2014/15", 26, "Luis Enrique"),
    ("valverde_1718", "Ernesto Valverde · 2017/18", 1, "Valverde"),
    ("setien_1920", "Quique Setién · 2019/20", 42, "Setién"),
    ("koeman_2021", "Ronald Koeman · 2020/21", 90, "Koeman"),
]
NOTES = {"vilanova_1213": "StatsBomb names the manager for only 4 of these matches; all Barça matches of the "
                          "season are used (Jordi Roura stood in during Vilanova's illness)."}
NX, NY, NDIR = 60, 40, 16
CELL = 2.0          # StatsBomb units per cell
STEP = 0.5          # walk step along each pass/carry
MAX_SPEED = 40.0    # units/s; caps rare timing glitches (0-duration events)
HERE = Path(__file__).parent
OUT = HERE / "flow_data.json"


def _get_json(url: str):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def matches_for(season_id: int, manager: str | None) -> list[dict]:
    ms = _get_json(f"{RAW}/matches/{LA_LIGA}/{season_id}.json")
    out = []
    for m in ms:
        side = "home_team" if m["home_team"]["home_team_name"] == TEAM else (
            "away_team" if m["away_team"]["away_team_name"] == TEAM else None)
        if side is None:
            continue
        names = " ".join((c.get("nickname") or "") + " " + c.get("name", "") for c in m[side].get("managers") or [])
        if manager is None or manager in names:
            out.append(m)
    return out


def extract(match_id: int, cache: Path) -> list[tuple]:
    """(kind, x0, y0, x1, y1, duration) for Barça passes/carries in Barça possession. Cached."""
    f = cache / f"{match_id}.csv.gz"
    if not f.exists():
        rows = []
        for e in _get_json(f"{RAW}/events/{match_id}.json"):
            t = e["type"]["name"]
            if t not in ("Pass", "Carry") or e["team"]["name"] != TEAM or e["possession_team"]["name"] != TEAM:
                continue
            if t == "Pass" and (e["pass"].get("type") or {}).get("name") in ("Corner", "Kick Off"):
                continue
            end = e["pass"]["end_location"] if t == "Pass" else e["carry"]["end_location"]
            rows.append((t, *e["location"][:2], *end[:2], e.get("duration") or 0.0))
        tmp = f.with_suffix(".tmp")
        with gzip.open(tmp, "wt", newline="") as fh:
            csv.writer(fh).writerows(rows)
        tmp.replace(f)
    with gzip.open(f, "rt") as fh:
        return [(r[0], *map(float, r[1:])) for r in csv.reader(fh)]


def accumulate(events: list[tuple]) -> tuple[np.ndarray, np.ndarray]:
    travel = np.zeros((NY, NX, NDIR))
    speed_w = np.zeros((NY, NX, NDIR))
    for _, x0, y0, x1, y1, dur in events:
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist < 1.0:  # sub-yard touches carry no direction
            continue
        d = int(round(math.atan2(dy, dx) / (2 * math.pi) * NDIR)) % NDIR
        spd = min(dist / dur, MAX_SPEED) if dur > 0.05 else MAX_SPEED
        n = max(int(dist / STEP), 1)
        seg = dist / n
        for i in range(n):
            px, py = x0 + dx * (i + 0.5) / n, y0 + dy * (i + 0.5) / n
            cx, cy = min(max(int(px / CELL), 0), NX - 1), min(max(int(py / CELL), 0), NY - 1)
            travel[cy, cx, d] += seg
            speed_w[cy, cx, d] += seg * spd
    return travel, speed_w


def _u16(a: np.ndarray) -> str:
    return base64.b64encode(np.clip(np.round(a), 0, 65535).astype("<u2").tobytes()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=HERE / ".cache")
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    out = {"grid": {"nx": NX, "ny": NY, "ndir": NDIR, "cell": CELL, "pitch": [120, 80],
                    "travel_scale": 1000, "speed_scale": 100, "units": "StatsBomb units (yards)"},
           "source": "StatsBomb open data (La Liga, matches released by StatsBomb)", "groups": []}
    for key, label, season_id, manager in GROUPS:
        ms = matches_for(season_id, manager)
        with cf.ThreadPoolExecutor(4) as ex:
            evs = list(ex.map(lambda m: extract(m["match_id"], args.cache), ms))
        travel, speed_w = np.zeros((NY, NX, NDIR)), np.zeros((NY, NX, NDIR))
        n_pass = n_carry = 0
        for e in evs:
            t, s = accumulate(e)
            travel += t
            speed_w += s
            n_pass += sum(1 for r in e if r[0] == "Pass")
            n_carry += sum(1 for r in e if r[0] == "Carry")
        n = len(ms)
        spd = np.divide(speed_w, travel, out=np.zeros_like(travel), where=travel > 0)
        out["groups"].append({
            "key": key, "label": label, "matches": n, "passes": n_pass, "carries": n_carry,
            "note": NOTES.get(key, ""),
            # little-endian uint16, layout [y][x][dir]: travel per match in 1/1000 units, speed in 1/100 units/s
            "travel": _u16(travel / n * 1000),
            "speed": _u16(spd * 100),
        })
        print(f"{label}: {n} matches, {n_pass} passes, {n_carry} carries")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
