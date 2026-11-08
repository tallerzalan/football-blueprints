# FC Barcelona under Hansi Flick (Streamlit)

All-competition dashboard for 2024/25, 2025/26 and 2026/27.

## Run
    pip install -r requirements.txt
    streamlit run barca-flick/app.py   # from the repo root

## Tabs
Overview (record by season/competition) · Form & streaks · La Liga (points race vs betting-market
expectation, position, home/away, upsets, tables) · Match stats (shots, SoT, corners, fouls, cards,
xG for 2026/27, league ranks) · Europe & cups (league phase, two-legged ties, record by country) ·
Players 2025/26 (apps, minutes, goals, pens, cards, goal timing, game states, referees, attendance) ·
Opponents · Match log (CSV download) · Possession flow · Data & coverage

## Data
- football-data.co.uk La Liga CSVs (stats + odds), fetched live
- openfootball (public domain): Champions League 2024/25–2025/26, Copa del Rey 2024/25,
  La Liga 2025/26 detailed file, fetched live
- `extra_matches.csv`: Supercopa 2024/25–2025/26 and Copa del Rey 2025/26 from Wikipedia season pages
  (refresh: `python barca-flick/update_from_wikipedia.py`); add your own rows too
- StatsBomb open data (Possession flow tab): Barça La Liga passes and carries, one season per coach
  2007/08–2020/21. Rebuild with `python barca-flick/flow/prepare_flow.py` (downloads ~250 matches once,
  cached). The animation is plain HTML/JS canvas in `flow/flow.html`, after the
  [possession-flow blueprint](../possession-flow/). Please credit StatsBomb when sharing it.
- `data/`: bundled copies of every live file, used automatically when a source is unreachable
  (refresh: `python barca-flick/refresh_snapshot.py`)

Fetched live, cached 6 h. Unofficial; verify important numbers with official sources.
