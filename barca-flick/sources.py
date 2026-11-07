"""Data loading for the Barça (Flick era) dashboard.

Sources (all fetched live, nothing invented):
  * football-data.co.uk  La Liga CSVs: scores, shots, shots on target, fouls, corners,
                         cards, average pre-match odds; xG from 2026/27 only.
  * openfootball (GitHub, public domain):
        champions-league/<season>/cl.txt   UCL scores (2024/25, 2025/26)
        espana/<season>/cup.txt            Copa del Rey scores (2024/25)
        espana/2025-26/1-liga-full.txt     La Liga 2025/26 line-ups, scorers, cards,
                                           referees, venues, attendance
  * extra_matches.csv (optional, local)    matches you add by hand for missing competitions
"""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import requests

TEAM_FD = "Barcelona"
SEASONS = ["2024/25", "2025/26", "2026/27"]          # Flick took over in summer 2024
FD_CODE = {"2024/25": "2425", "2025/26": "2526", "2026/27": "2627"}
OF_DIR = {"2024/25": "2024-25", "2025/26": "2025-26", "2026/27": "2026-27"}
FD_URL = "https://www.football-data.co.uk/mmz4281/{code}/SP1.csv"
OF_RAW = "https://raw.githubusercontent.com/openfootball/{repo}/master/{path}"

# (competition, repo, file) per season, only where the file exists upstream
OF_COMPS = {
    "Champions League": ("champions-league", "cl.txt"),
    "Copa del Rey": ("espana", "cup.txt"),
}
EXTRA_CSV = Path(__file__).with_name("extra_matches.csv")
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _get(url: str) -> str | None:
    r = requests.get(url, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def season_of(d) -> str:
    d = pd.Timestamp(d)
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}/{(y + 1) % 100:02d}"


def _result(gf, ga):
    return "W" if gf > ga else ("L" if gf < ga else "D")


# --------------------------------------------------------------------------- La Liga (football-data)
FD_STATS = {  # our name: (home col, away col)
    "goals": ("FTHG", "FTAG"), "ht_goals": ("HTHG", "HTAG"), "shots": ("HS", "AS"),
    "sot": ("HST", "AST"), "fouls": ("HF", "AF"), "corners": ("HC", "AC"),
    "yellows": ("HY", "AY"), "reds": ("HR", "AR"), "xg": ("HxG", "AxG"),
}


def load_fd_league(season: str) -> pd.DataFrame:
    """Whole league, one row per match, as published by football-data.co.uk."""
    txt = _get(FD_URL.format(code=FD_CODE[season]))
    df = pd.read_csv(io.StringIO(txt.lstrip("﻿")))
    df = df.dropna(subset=["HomeTeam", "FTHG"]).copy()
    df["date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df["season"] = season
    for col in ("AvgH", "AvgD", "AvgA"):
        if col not in df:
            df[col] = df.get("B365" + col[-1])
    return df


def team_rows(fd: pd.DataFrame, team: str) -> pd.DataFrame:
    """One row per match from `team`'s perspective, with *_for / *_against stats."""
    out = []
    for venue, side, other in (("Home", 0, 1), ("Away", 1, 0)):
        sub = fd[fd["HomeTeam" if side == 0 else "AwayTeam"] == team]
        r = pd.DataFrame({
            "date": sub["date"], "season": sub["season"], "venue": venue, "team": team,
            "opponent": sub["AwayTeam" if side == 0 else "HomeTeam"],
        })
        for k, cols in FD_STATS.items():
            if cols[0] in sub:
                r[f"{k}_for"] = pd.to_numeric(sub[cols[side]], errors="coerce")
                r[f"{k}_against"] = pd.to_numeric(sub[cols[other]], errors="coerce")
            else:
                r[f"{k}_for"] = r[f"{k}_against"] = float("nan")
        # implied probabilities from average pre-match odds, normalised to remove the margin
        inv = 1 / sub[["AvgH", "AvgD", "AvgA"]].astype(float)
        inv = inv.div(inv.sum(axis=1), axis=0)
        r["p_win"] = inv["AvgH" if side == 0 else "AvgA"].values
        r["p_draw"] = inv["AvgD"].values
        r["p_loss"] = inv["AvgA" if side == 0 else "AvgH"].values
        out.append(r)
    t = pd.concat(out).sort_values("date").reset_index(drop=True)
    t["gf"], t["ga"] = t["goals_for"].astype(int), t["goals_against"].astype(int)
    t["result"] = [_result(a, b) for a, b in zip(t["gf"], t["ga"])]
    t["points"] = t["result"].map({"W": 3, "D": 1, "L": 0})
    t["xpts_market"] = 3 * t["p_win"] + t["p_draw"]
    return t


def league_table(fd: pd.DataFrame, upto=None) -> pd.DataFrame:
    """Table ranked by Pts, GD, GF. (La Liga officially uses head-to-head first.)"""
    p = fd if upto is None else fd[fd["date"] <= upto]
    rows = pd.concat([
        pd.DataFrame({"team": p["HomeTeam"], "gf": p["FTHG"], "ga": p["FTAG"]}),
        pd.DataFrame({"team": p["AwayTeam"], "gf": p["FTAG"], "ga": p["FTHG"]}),
    ])
    rows["W"], rows["D"], rows["L"] = (rows.gf > rows.ga) * 1, (rows.gf == rows.ga) * 1, (rows.gf < rows.ga) * 1
    t = rows.groupby("team").agg(P=("W", "size"), W=("W", "sum"), D=("D", "sum"), L=("L", "sum"),
                                 GF=("gf", "sum"), GA=("ga", "sum"))
    t["GD"], t["Pts"] = t.GF - t.GA, 3 * t.W + t.D
    t = t.sort_values(["Pts", "GD", "GF"], ascending=False).astype(int)
    t.insert(0, "Pos", range(1, len(t) + 1))
    return t.reset_index()


def league_team_averages(fd: pd.DataFrame) -> pd.DataFrame:
    """Per-game averages for every team in the league (for ranking Barça)."""
    rows = pd.concat([team_rows(fd, t) for t in sorted(set(fd.HomeTeam) | set(fd.AwayTeam))])
    cols = [c for c in rows.columns if c.endswith(("_for", "_against"))] + ["points"]
    avg = rows.groupby("team")[cols].mean()
    avg["games"] = rows.groupby("team").size()
    avg["shot_conv_for"] = rows.groupby("team")["goals_for"].sum() / rows.groupby("team")["shots_for"].sum()
    avg["sot_ratio_for"] = rows.groupby("team")["sot_for"].sum() / rows.groupby("team")["shots_for"].sum()
    return avg


# --------------------------------------------------------------------------- openfootball text fixtures
SCORE_RE = re.compile(
    r"^(?P<a>\d+)-(?P<b>\d+)"
    r"(?:\s+pen\.\s+(?P<et_a>\d+)-(?P<et_b>\d+)\s+a\.e\.t\.|\s+(?P<aet>a\.e\.t\.))?"
    r"(?:\s+\((?P<paren>[^)]*)\))?\s*$"
)
LINE_RE = re.compile(r"^\s+(?:\d{1,2}:\d{2}\s+)?(?P<home>.+?)\s+v\s+(?P<away>.+?)\s{2,}(?P<score>\d+-\d+.*)$")
DATE_RE = re.compile(r"^\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
TEAM_SUFFIX = re.compile(r"\s+\([A-Z]{3}\)$")


def parse_score(s: str) -> dict | None:
    m = SCORE_RE.match(s.strip())
    if not m:
        return None
    a, b = int(m["a"]), int(m["b"])
    paren = [x.strip() for x in (m["paren"] or "").split(",") if x.strip()]
    if m["et_a"]:                       # "4-3 pen. 1-1 a.e.t. (1-1, 0-1)"
        return {"hg": int(m["et_a"]), "ag": int(m["et_b"]), "pens": (a, b), "aet": True,
                "ht": paren[-1] if paren else None}
    if m["aet"]:                        # "3-2 a.e.t. (2-2, 1-0)"
        return {"hg": a, "ag": b, "pens": None, "aet": True, "ht": paren[-1] if paren else None}
    return {"hg": a, "ag": b, "pens": None, "aet": False, "ht": paren[0] if paren else None}


def parse_of_fixtures(txt: str, competition: str, season: str) -> pd.DataFrame:
    start_year = int(season[:4])
    year, last_month, rnd, cur_date, rows = start_year, None, None, None, []
    for line in txt.splitlines():
        if line.startswith("▪"):
            rnd = line[1:].strip()
            continue
        dm = DATE_RE.match(line)
        if dm:
            mon, day = MONTHS[dm[1]], int(dm[2])
            if dm[3]:
                year = int(dm[3])
            elif last_month and mon < last_month:
                year += 1
            last_month, cur_date = mon, date(year, mon, day)
            continue
        lm = LINE_RE.match(line)
        if not lm or cur_date is None:
            continue
        raw_home, raw_away = lm["home"].strip(), lm["away"].strip()
        home, away = TEAM_SUFFIX.sub("", raw_home), TEAM_SUFFIX.sub("", raw_away)
        cm = re.search(r"\(([A-Z]{3})\)$", raw_away if home == "FC Barcelona" else raw_home)
        if "FC Barcelona" not in (home, away):
            continue
        sc = parse_score(lm["score"])
        if not sc:
            continue
        is_home = home == "FC Barcelona"
        gf, ga = (sc["hg"], sc["ag"]) if is_home else (sc["ag"], sc["hg"])
        ht_f = ht_a = None
        if sc["ht"] and re.match(r"^\d+-\d+$", sc["ht"]):
            h1, a1 = map(int, sc["ht"].split("-"))
            ht_f, ht_a = (h1, a1) if is_home else (a1, h1)
        neutral = rnd is not None and rnd.split(",")[-1].strip() == "Final"
        note = ""
        if sc["pens"]:
            pf, pa = sc["pens"] if is_home else sc["pens"][::-1]
            note = f"{'won' if pf > pa else 'lost'} {pf}-{pa} on pens"
        elif sc["aet"]:
            note = "a.e.t."
        rows.append({
            "date": pd.Timestamp(cur_date), "season": season, "competition": competition,
            "round": rnd, "opponent": away if is_home else home,
            "venue": "Neutral" if neutral else ("Home" if is_home else "Away"),
            "gf": gf, "ga": ga, "ht_for": ht_f, "ht_against": ht_a, "note": note,
            "opp_country": cm[1] if cm else ("ESP" if competition == "Copa del Rey" else None),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- La Liga 2025/26 detailed file
FULL_PATH = "2025-26/1-liga-full.txt"
FULL_SEASON = "2025/26"
TEAM_FULL = "Barcelona"
HEADER_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})\s+\d{1,2}:\d{2}.*?@\s+(?P<venue>.+?)(?:,\s+Att:\s+(?P<att>\d+))?\s*$")
MATCH_FULL_RE = re.compile(r"^  (?P<home>\S.*?)\s+v\s+(?P<away>.+?)\s{2,}(?P<score>\d+-\d+.*)$")
MIN_RE = re.compile(r"^(\d+)(?:\+(\d+))?'")


def _minute(tok: str, exact: bool = False) -> float:
    """45+2' -> 45 (or 45.02 with exact=True, which keeps stoppage-time goals in order)."""
    m = MIN_RE.match(tok.strip())
    if not m:
        return 90
    if exact:
        return int(m[1]) + (int(m[2]) / 100 if m[2] else 0)
    return min(int(m[1]), 90)


def _split_top(s: str, seps=(",", " - ")) -> list[str]:
    """Split on separators that are not inside parentheses."""
    out, depth, buf, i = [], 0, "", 0
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0:
            hit = next((sp for sp in seps if s.startswith(sp, i)), None)
            if hit:
                out.append(buf)
                buf, i = "", i + len(hit)
                continue
        buf += c
        i += 1
    out.append(buf)
    return [x.strip() for x in out if x.strip()]


def _clean_name(n: str) -> str:
    return re.sub(r"\s+", " ", n.replace("[c]", "")).strip()


def _parse_lineup(text: str) -> list[dict]:
    """'GK - A (58' B (70' C)), D [c] - ...' -> list of {player, start, on, off, captain}."""
    players = []
    for entry in _split_top(text):
        on, starter, rest = 0, True, entry
        while rest:
            k = rest.find("(")
            name = rest if k < 0 else rest[:k]
            captain = "[c]" in name
            nxt = None
            if k >= 0:
                inner = rest[k + 1: rest.rfind(")")].strip()
                nxt_min = _minute(inner)
                nxt = inner[inner.find("'") + 1:].strip()
            players.append({"player": _clean_name(name), "start": starter, "on": on,
                            "off": nxt_min if nxt is not None else 90, "captain": captain})
            if nxt is None:
                break
            on, starter, rest = nxt_min, False, nxt
    return players


def _parse_events(text: str, exact: bool = False) -> list[tuple[str, float, str]]:
    """'A 29', 56', B 53'(p)' -> [(A,29,''), (A,56,''), (B,53,'p')]."""
    out, name = [], None
    for tok in _split_top(text, seps=(",",)):
        m = re.match(r"^(?P<name>.*?)\s*(?P<min>\d+(?:\+\d+)?')\s*(?:\((?P<tag>[a-z]+)\))?$", tok)
        if not m:
            continue
        if m["name"]:
            name = _clean_name(m["name"])
        out.append((name, _minute(m["min"], exact), m["tag"] or ""))
    return out


def parse_full_league(txt: str) -> dict[str, pd.DataFrame]:
    """Barça-only match details for La Liga 2025/26."""
    blocks, cur = [], None
    for line in txt.splitlines():
        hm = HEADER_RE.match(line)
        if hm:
            cur = {"header": hm, "lines": []}
            blocks.append(cur)
        elif cur is not None:
            cur["lines"].append(line)

    matches, apps, goals, cards = [], [], [], []
    for b in blocks:
        lines = b["lines"]
        mm = next((MATCH_FULL_RE.match(l) for l in lines if MATCH_FULL_RE.match(l)), None)
        if not mm or TEAM_FULL not in (mm["home"].strip(), mm["away"].strip()):
            continue
        home, away = mm["home"].strip(), mm["away"].strip()
        sc = parse_score(mm["score"])
        mon, day = MONTHS[b["header"][1]], int(b["header"][2])
        d = pd.Timestamp(date(2025 if mon >= 7 else 2026, mon, day))
        is_home = home == TEAM_FULL
        opp = away if is_home else home
        body = "\n".join(lines)

        # scorers: "(home ...; away ...)" on the line(s) directly under the match line
        idx = next(i for i, l in enumerate(lines) if MATCH_FULL_RE.match(l))
        gtxt, depth = "", 0
        if idx + 1 < len(lines) and lines[idx + 1].strip().startswith("("):
            for l in lines[idx + 1:]:
                gtxt += " " + l.strip()
                depth += l.count("(") - l.count(")")
                if depth <= 0:
                    break
        gtxt = gtxt.strip()[1:-1] if gtxt else ""
        g_home = g_away = []
        if gtxt:
            parts = _split_top(gtxt, seps=(";",))
            if len(parts) == 2:
                g_home, g_away = _parse_events(parts[0], True), _parse_events(parts[1], True)
            elif sc["hg"] and not sc["ag"]:
                g_home = _parse_events(parts[0], True)
            elif sc["ag"] and not sc["hg"]:
                g_away = _parse_events(parts[0], True)
        for side, evs in (("for" if is_home else "against", g_home), ("against" if is_home else "for", g_away)):
            for name, minute, tag in evs:
                goals.append({"date": d, "opponent": opp, "side": side, "player": name,
                              "minute": minute, "penalty": tag == "p", "own_goal": tag == "og"})

        # line-ups & cards per team block
        team_blocks = re.split(r"\n(?=[^\s].*?: )", body)
        for tb in team_blocks:
            head = tb.split(":", 1)[0].strip()
            if head not in (home, away):
                continue
            lineup_txt, card_lines = [], []
            for l in tb.split(":", 1)[1].splitlines():
                s = l.strip()
                if s.startswith("Refs:"):
                    break
                if re.match(r"^(Yellow|Red|Yellow-Red):", s):
                    card_lines.append(s)
                elif not s:
                    continue
                elif card_lines:              # wrapped card list
                    card_lines[-1] += " " + s
                else:
                    lineup_txt.append(s)
            if head != TEAM_FULL:
                continue
            ps = _parse_lineup(" ".join(lineup_txt))
            reds = {}
            for cl in card_lines:
                kind, rest = cl.split(":", 1)
                for name, minute, _ in _parse_events(rest):
                    cards.append({"date": d, "opponent": opp, "player": name, "minute": minute,
                                  "card": kind.strip()})
                    if kind.strip() in ("Red", "Yellow-Red"):
                        reds[name] = minute
            for p in ps:
                off = min(p["off"], reds.get(p["player"], 99))
                apps.append({"date": d, "opponent": opp, **p, "off": off,
                             "minutes": max(off - p["on"], 0)})

        refs = re.search(r"Refs:\s*([^,\n]+)", body)
        hd = b["header"]
        matches.append({
            "date": d, "opponent": opp, "venue": "Home" if is_home else "Away",
            "gf": sc["hg"] if is_home else sc["ag"], "ga": sc["ag"] if is_home else sc["hg"],
            "stadium": hd["venue"].strip(), "attendance": int(hd["att"]) if hd["att"] else None,
            "referee": refs[1].strip() if refs else None,
        })
    return {k: pd.DataFrame(v) for k, v in
            {"matches": matches, "apps": apps, "goals": goals, "cards": cards}.items()}


# --------------------------------------------------------------------------- assembly
def load_all() -> dict:
    fd = {s: load_fd_league(s) for s in SEASONS}
    liga = pd.concat([team_rows(fd[s], TEAM_FD) for s in SEASONS], ignore_index=True)
    liga["competition"], liga["round"], liga["note"] = "La Liga", None, ""
    liga = liga.rename(columns={"ht_goals_for": "ht_for", "ht_goals_against": "ht_against"})

    other, coverage = [], []
    for s in SEASONS:
        coverage.append({"season": s, "competition": "La Liga", "source": "football-data.co.uk",
                         "games": int((liga.season == s).sum())})
        for comp, (repo, fname) in OF_COMPS.items():
            txt = _get(OF_RAW.format(repo=repo, path=f"{OF_DIR[s]}/{fname}"))
            df = parse_of_fixtures(txt, comp, s) if txt else pd.DataFrame()
            if len(df):
                other.append(df)
            coverage.append({"season": s, "competition": comp,
                             "source": "openfootball" if len(df) else "not available",
                             "games": len(df)})
        coverage.append({"season": s, "competition": "Supercopa de España", "source": "not available",
                         "games": 0})

    if EXTRA_CSV.exists():
        ex = pd.read_csv(EXTRA_CSV, parse_dates=["date"])
        if len(ex):
            ex["season"] = ex["date"].map(season_of)
            ex["note"] = ex["note"].fillna("") if "note" in ex else ""
            other.append(ex)
            for (s, c), n in ex.groupby(["season", "competition"]).size().items():
                coverage.append({"season": s, "competition": c, "source": "extra_matches.csv", "games": n})

    allm = pd.concat([liga] + other, ignore_index=True).sort_values("date").reset_index(drop=True)
    allm["result"] = [_result(a, b) for a, b in zip(allm.gf, allm.ga)]
    allm["score"] = allm.gf.astype(int).astype(str) + "–" + allm.ga.astype(int).astype(str)
    cov = pd.DataFrame(coverage)
    cov = cov.groupby(["season", "competition"], as_index=False).agg(
        source=("source", lambda x: " + ".join(sorted(set(x) - {"not available"})) or "not available"),
        games=("games", "sum"))

    full_txt = _get(OF_RAW.format(repo="espana", path=FULL_PATH))
    detail = parse_full_league(full_txt) if full_txt else None
    return {"fd": fd, "matches": allm, "coverage": cov, "detail": detail}
