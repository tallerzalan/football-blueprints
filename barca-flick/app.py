import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

import sources as S

st.set_page_config(page_title="Barça under Flick", page_icon="⚽", layout="wide")

BLAU, GRANA, GOLD = "#004D98", "#A50044", "#EDBB00"
SEASON_COLORS = {"2024/25": GOLD, "2025/26": BLAU, "2026/27": GRANA}
RESULT_COLORS = {"W": "#2E9E5B", "D": "#B8B8B8", "L": "#D64545"}
COMP_SYMBOL = {"La Liga": "circle", "Champions League": "star", "Copa del Rey": "diamond",
               "Supercopa de España": "square"}
PCT = st.column_config.NumberColumn(format="%.0f%%")
F2 = st.column_config.NumberColumn(format="%.2f")


@st.cache_data(ttl=6 * 3600, show_spinner="Fetching data from football-data.co.uk and openfootball…")
def load():
    d = S.load_all()
    d["tables"] = {s: S.league_table(d["fd"][s]) for s in S.SEASONS}
    d["league_avg"] = {s: S.league_team_averages(d["fd"][s]) for s in S.SEASONS}
    liga = d["matches"][d["matches"].competition == "La Liga"].copy()
    liga["position"] = [
        int(S.league_table(d["fd"][s], dt).set_index("team").loc[S.TEAM_FD, "Pos"])
        for s, dt in zip(liga.season, liga.date)
    ]
    d["liga"] = liga
    return d


D = load()
M = D["matches"]


def record(df: pd.DataFrame) -> dict:
    n = len(df)
    w, dr, l = (df.result == "W").sum(), (df.result == "D").sum(), (df.result == "L").sum()
    return {"P": n, "W": w, "D": dr, "L": l, "GF": int(df.gf.sum()), "GA": int(df.ga.sum()),
            "GD": int(df.gf.sum() - df.ga.sum()), "Win %": 100 * w / n if n else np.nan,
            "GF/g": df.gf.mean() if n else np.nan, "GA/g": df.ga.mean() if n else np.nan,
            "Clean sheets": int((df.ga == 0).sum()), "Blanks": int((df.gf == 0).sum())}


def streaks(df: pd.DataFrame) -> pd.DataFrame:
    """Longest runs in date order, within the matches in the data."""
    df = df.sort_values("date")
    tests = {
        "Wins": df.result == "W", "Unbeaten": df.result != "L", "Without a win": df.result != "W",
        "Scoring": df.gf > 0, "Clean sheets": df.ga == 0, "Scoring 3+": df.gf >= 3,
    }
    rows = []
    for name, ok in tests.items():
        best, cur, start, best_span = 0, 0, None, (None, None)
        for dt, flag in zip(df.date, ok):
            if flag:
                cur, start = cur + 1, start if cur else dt
                if cur > best:
                    best, best_span = cur, (start, dt)
            else:
                cur = 0
        rows.append({"Streak": name, "Games": best,
                     "From": best_span[0].date() if best else None,
                     "To": best_span[1].date() if best else None})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ sidebar
st.sidebar.title("Barça under Hansi Flick")
seasons = st.sidebar.multiselect("Seasons", S.SEASONS, default=S.SEASONS)
comps_avail = list(dict.fromkeys(["La Liga", "Champions League", "Copa del Rey", "Supercopa de España"]
                                  + sorted(M.competition.unique())))
comps_avail = [c for c in comps_avail if c in set(M.competition)]
comps = st.sidebar.multiselect("Competitions", comps_avail, default=comps_avail)
venues = st.sidebar.multiselect("Venue", ["Home", "Away", "Neutral"], default=["Home", "Away", "Neutral"])
st.sidebar.divider()
st.sidebar.caption(
    "Sources: [football-data.co.uk](https://www.football-data.co.uk) (La Liga match stats & odds) · "
    "[openfootball](https://github.com/openfootball) (Champions League, Copa del Rey, La Liga 2025/26 "
    "line-ups & scorers). See the **Data & coverage** tab for what is missing."
)
if not seasons or not comps or not venues:
    st.info("Pick at least one season, competition and venue.")
    st.stop()
F = M[M.season.isin(seasons) & M.competition.isin(comps) & M.venue.isin(venues)]

# ------------------------------------------------------------------ header
st.title("FC Barcelona under Hansi Flick")
last = M.date.max()
st.caption(f"{len(M)} matches in the data, latest {last:%d %b %Y}. "
           "Competitions without a free source are missing; see the coverage strip below.")
FL = D["fetch_log"]
fallback = FL[~FL.status.isin(["live", "not published (404)"])] if len(FL) else FL
if D.get("conflicts"):
    st.error("Score disagreement between extra_matches.csv and a live source (live source used): "
             + "; ".join(D["conflicts"]))
if len(fallback):
    st.warning(f"{len(fallback)} source(s) could not be fetched live and use the snapshot bundled in the repo, "
               "so recent matches may be missing. Details in the Data & coverage tab.")

cov = D["coverage"].pivot(index="competition", columns="season", values="games").reindex(columns=S.SEASONS)
cov_txt = cov.map(lambda v: "– none in data" if (pd.isna(v) or v == 0) else f"✓ {int(v)}")
with st.expander("Coverage: matches per competition and season", expanded=False):
    st.dataframe(cov_txt, use_container_width=True)
    st.caption("2026/27 Copa del Rey and Supercopa: no Barça matches played yet when the data was last updated. "
               "Champions League 2026/27: no free source reachable yet. Sources per row in the Data & coverage tab.")

# KPI row
k = record(F)
c = st.columns(4) + st.columns(4)
c[0].metric("Matches", k["P"])
c[1].metric("W-D-L", f"{k['W']}-{k['D']}-{k['L']}")
c[2].metric("Win rate", f"{k['Win %']:.0f}%" if k["P"] else "–")
c[3].metric("Goals", f"{k['GF']}:{k['GA']}")
c[4].metric("Scored / game", f"{k['GF/g']:.2f}" if k["P"] else "–")
c[5].metric("Conceded / game", f"{k['GA/g']:.2f}" if k["P"] else "–")
c[6].metric("Clean sheets", k["Clean sheets"])
c[7].metric("Failed to score", k["Blanks"])

tabs = st.tabs(["Overview", "Form & streaks", "La Liga", "Match stats (La Liga)",
                "Europe & cups", "Players 2025/26", "Opponents", "Match log", "Possession flow",
                "Data & coverage"])

# ================================================================== Overview
with tabs[0]:
    rows = []
    for (s, comp), g in F.groupby(["season", "competition"]):
        rows.append({"Season": s, "Competition": comp, **record(g)})
    for s, g in F.groupby("season"):
        rows.append({"Season": s, "Competition": "All (in data)", **record(g)})
    rec = pd.DataFrame(rows).sort_values(["Season", "Competition"])
    st.subheader("Record by season and competition")
    st.dataframe(rec, hide_index=True, use_container_width=True,
                 column_config={"Win %": PCT, "GF/g": F2, "GA/g": F2})

    c1, c2 = st.columns(2)
    with c1:
        r = F.groupby(["season", "competition", "result"]).size().reset_index(name="games")
        fig = px.bar(r, x="season", y="games", color="result", facet_col="competition",
                     color_discrete_map=RESULT_COLORS, category_orders={"result": ["W", "D", "L"]},
                     title="Results", text="games")
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        g = F.groupby(["season", "competition"])[["gf", "ga"]].mean().reset_index()
        g = g.melt(id_vars=["season", "competition"], var_name="k", value_name="per game")
        g["k"] = g.k.map({"gf": "Scored", "ga": "Conceded"})
        fig = px.bar(g, x="competition", y="per game", color="season", facet_col="k", barmode="group",
                     color_discrete_map=SEASON_COLORS, title="Goals per game",
                     text=g["per game"].round(2))
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Honours visible in the data")
    notes = []
    for s in seasons:
        t = D["tables"][s]
        pos = int(t.set_index("team").loc[S.TEAM_FD, "Pos"])
        games = int(t.set_index("team").loc[S.TEAM_FD, "P"])
        done = games == 38
        notes.append(f"**{s} La Liga**: {'finished' if done else f'currently (after {games} games)'} "
                     f"{pos}{'st' if pos == 1 else 'th' if pos > 3 else ('nd' if pos == 2 else 'rd')} "
                     f"in the table computed from the data.")
        for comp in ["Champions League", "Copa del Rey", "Supercopa de España"]:
            g = M[(M.season == s) & (M.competition == comp)].sort_values("date")
            if len(g):
                lastm = g.iloc[-1]
                final_note = ""
                if lastm["round"] and lastm["round"].split(",")[-1].strip() == "Final":
                    final_note = " – **won the final**" if lastm.result == "W" else " – lost the final"
                notes.append(f"**{s} {comp}**: last game in the data is the {lastm['round']} vs "
                             f"{lastm.opponent} ({lastm.score}{', ' + lastm.note if lastm.note else ''})"
                             f"{final_note}.")
    st.markdown("\n".join(f"- {n}" for n in notes))
    st.caption("Derived only from match data. Trophies from competitions not in the data (e.g. Supercopa) "
               "are not shown. Check official sources before quoting.")

# ================================================================== Form & streaks
with tabs[1]:
    G = F.sort_values("date").copy()
    G["pts"] = G.result.map({"W": 3, "D": 1, "L": 0})
    G["form10"] = G.pts.rolling(10, min_periods=3).mean()
    fig = go.Figure()
    for comp, g in G.groupby("competition"):
        fig.add_scatter(x=g.date, y=g.gf - g.ga, mode="markers", name=comp,
                        marker=dict(symbol=COMP_SYMBOL.get(comp, "circle"), size=10,
                                    color=[RESULT_COLORS[r] for r in g.result],
                                    line=dict(width=1, color="#333")),
                        customdata=g[["opponent", "venue", "score", "round"]].fillna(""),
                        hovertemplate="%{x|%d %b %Y} · " + comp + "<br>%{customdata[1]} vs %{customdata[0]}"
                                      " %{customdata[2]}<br>%{customdata[3]}<extra></extra>")
    fig.add_scatter(x=G.date, y=G.form10, name="Points/game, last 10 (right axis)", yaxis="y2",
                    line=dict(color=BLAU, width=2, shape="spline"))
    fig.update_layout(title="Every match: goal difference (colour = result, shape = competition)",
                      yaxis=dict(title="Goal difference", zeroline=True),
                      yaxis2=dict(overlaying="y", side="right", range=[0, 3.1], tickmode="linear", tick0=0, dtick=0.5, title="Pts/game", showgrid=False),
                      height=460, legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Points per game uses 3/1/0 for every competition so cup and league form can be compared. "
               "Gaps in coverage mean form lines skip games not in the data.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Longest streaks")
        st.dataframe(streaks(G), hide_index=True, use_container_width=True)
        st.caption("Within the matches in the data and current filters; a missing game (e.g. Supercopa) "
                   "could break or extend a real streak.")
    with c2:
        st.subheader("Biggest wins and defeats")
        G["margin"] = G.gf - G.ga
        top = pd.concat([G.nlargest(5, ["margin", "gf"]), G.nsmallest(5, ["margin"])])
        st.dataframe(top[["date", "competition", "opponent", "venue", "score", "note"]], hide_index=True,
                     use_container_width=True,
                     column_config={"date": st.column_config.DateColumn(format="DD MMM YYYY")})

    c1, c2 = st.columns(2)
    with c1:
        sc = G.groupby("score").size().reset_index(name="games").sort_values("games", ascending=False).head(15)
        st.plotly_chart(px.bar(sc, x="score", y="games", title="Most common scorelines (Barça first)",
                               color_discrete_sequence=[BLAU]), use_container_width=True)
    with c2:
        H = G.dropna(subset=["ht_for", "ht_against"]).copy()
        H["HT"] = np.select([H.ht_for > H.ht_against, H.ht_for < H.ht_against], ["Leading", "Trailing"], "Level")
        ht = H.groupby(["HT", "result"]).size().reset_index(name="games")
        fig = px.bar(ht, x="HT", y="games", color="result", color_discrete_map=RESULT_COLORS,
                     category_orders={"HT": ["Leading", "Level", "Trailing"], "result": ["W", "D", "L"]},
                     title="Final result by half-time situation", text="games")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"{len(H)} of {len(G)} matches have a half-time score.")

# ================================================================== La Liga
with tabs[2]:
    L = D["liga"][D["liga"].season.isin(seasons)]
    LV = L[L.venue.isin(venues)]
    fig = go.Figure()
    for s, g in L.groupby("season"):
        g = g.sort_values("date")
        n = np.arange(1, len(g) + 1)
        fig.add_scatter(x=n, y=g.points.cumsum(), name=f"{s} actual", line=dict(color=SEASON_COLORS[s], width=3),
                        customdata=g[["opponent", "venue", "score"]],
                        hovertemplate="Game %{x}: %{customdata[1]} vs %{customdata[0]} %{customdata[2]}"
                                      "<br>Points %{y}<extra>" + s + "</extra>")
        fig.add_scatter(x=n, y=g.xpts_market.cumsum(), name=f"{s} market-expected",
                        line=dict(color=SEASON_COLORS[s], dash="dot", width=2), hoverinfo="skip")
    fig.update_layout(title="Points race vs bookmakers' pre-match expectation", xaxis_title="League game",
                      yaxis_title="Points", height=440)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Dotted line: expected points from average pre-match odds (3 × P(win) + P(draw), "
               "bookmaker margin removed). Above it = beating the market's expectations.")

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for s, g in L.groupby("season"):
            fig.add_scatter(x=np.arange(1, len(g) + 1), y=g.position, name=s,
                            line=dict(color=SEASON_COLORS[s], width=3, shape="hv"))
        fig.update_layout(title="League position after each game", yaxis=dict(autorange="reversed", dtick=1),
                          xaxis_title="League game", height=380)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        rows = [{"Season": s, "Venue": v, **record(g), "Pts": int(g.points.sum()),
                 "Pts/g": g.points.mean(), "xPts (market)": g.xpts_market.sum()}
                for (s, v), g in L.groupby(["season", "venue"])]
        hv = pd.DataFrame(rows)
        fig = px.bar(hv, x="Venue", y="Pts/g", color="Season", barmode="group", color_discrete_map=SEASON_COLORS,
                     text=hv["Pts/g"].round(2), title="Points per game, home vs away")
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(hv[["Season", "Venue", "P", "W", "D", "L", "GF", "GA", "Pts", "Pts/g", "xPts (market)",
                     "Clean sheets"]], hide_index=True, use_container_width=True,
                 column_config={"Pts/g": F2, "xPts (market)": st.column_config.NumberColumn(format="%.1f")})

    st.subheader("Upsets: results furthest from the market")
    U = LV.copy()
    U["surprise"] = U.points - U.xpts_market
    U["P(win) %"] = 100 * U.p_win
    show = pd.concat([U.nsmallest(6, "surprise"), U.nlargest(4, "surprise")])
    st.dataframe(show[["date", "season", "opponent", "venue", "score", "P(win) %", "points", "surprise"]],
                 hide_index=True, use_container_width=True,
                 column_config={"date": st.column_config.DateColumn(format="DD MMM YYYY"), "P(win) %": PCT,
                                "surprise": st.column_config.NumberColumn("Pts vs expected", format="%+.2f")})

    st.subheader("League tables (computed from results)")
    tcols = st.columns(len(seasons))
    for col, s in zip(tcols, seasons):
        with col:
            st.markdown(f"**{s}**")
            t = D["tables"][s]
            st.dataframe(t.style.apply(lambda r: [f"background-color:{BLAU}33" if r.team == S.TEAM_FD else ""]
                                       * len(r), axis=1),
                         hide_index=True, use_container_width=True, height=38 + 35 * len(t))
    st.caption("Ranked by points, goal difference, goals scored. La Liga applies head-to-head first, so tied "
               "teams may be ordered differently from the official table.")

# ================================================================== Match stats
with tabs[3]:
    st.caption("Source: football-data.co.uk, La Liga only. xG is only published from 2026/27.")
    metrics = {"Goals": "goals", "Shots": "shots", "Shots on target": "sot", "Corners": "corners",
               "Fouls": "fouls", "Yellow cards": "yellows", "Red cards": "reds", "xG": "xg"}
    rows = []
    for s in seasons:
        A = D["league_avg"][s]
        for label, k in metrics.items():
            for side in ("for", "against"):
                col = f"{k}_{side}"
                if A[col].notna().sum() == 0:
                    continue
                # goals/shots/SoT/corners/xG: rank 1 = best (most for, fewest against)
                # fouls/cards: rank 1 = most, on both sides (no obvious "good" direction)
                asc = side == "against" and k not in ("fouls", "yellows", "reds")
                rank = A[col].rank(ascending=asc, method="min").loc[S.TEAM_FD]
                rows.append({"Season": s, "Metric": label, "Side": "Barça" if side == "for" else "Opponents",
                             "Barça per game": A.loc[S.TEAM_FD, col], "League avg": A[col].mean(),
                             "Rank (of 20)": int(rank)})
        for label, col in (("Shot conversion % (goals/shots)", "shot_conv_for"),
                           ("Shot accuracy % (on target/shots)", "sot_ratio_for")):
            rows.append({"Season": s, "Metric": label, "Side": "Barça",
                         "Barça per game": 100 * A.loc[S.TEAM_FD, col], "League avg": 100 * A[col].mean(),
                         "Rank (of 20)": int(A[col].rank(ascending=False, method="min").loc[S.TEAM_FD])})
    MS = pd.DataFrame(rows)
    piv = MS.pivot_table(index=["Metric", "Side"], columns="Season",
                         values=["Barça per game", "Rank (of 20)"]).round(2)
    st.subheader("Per-game numbers and league rank")
    st.dataframe(piv, use_container_width=True, height=38 + 35 * (len(piv) + 2))
    st.caption("Rank among 20 teams. Goals, shots, shots on target, corners, xG: rank 1 = best (most for Barça, "
               "fewest allowed). Fouls and cards: rank 1 = most (Barça side: committed by Barça; Opponents side: "
               "committed by opponents in Barça games).")

    s_pick = st.radio("Season for league comparison", seasons, horizontal=True, index=len(seasons) - 1)
    A = D["league_avg"][s_pick].reset_index()
    A["is_barca"] = np.where(A.team == S.TEAM_FD, "Barcelona", "Other")
    c1, c2 = st.columns(2)
    for col, (x, y, ttl) in zip((c1, c2), (("shots_for", "shots_against", "Shots for vs against per game"),
                                           ("sot_for", "sot_against", "Shots on target for vs against"))):
        with col:
            fig = px.scatter(A, x=x, y=y, text="team", color="is_barca",
                             color_discrete_map={"Barcelona": GRANA, "Other": "#9AA5B1"}, title=f"{ttl} ({s_pick})")
            fig.update_traces(textposition="top center", textfont_size=9)
            fig.update_layout(showlegend=False, height=460, xaxis_title="For (per game)",
                              yaxis_title="Against (per game)", yaxis_autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
    st.caption("Against-axis is reversed: top-right = dominant (many shots, few allowed).")

    L = D["liga"][D["liga"].season.isin(seasons) & D["liga"].venue.isin(venues)].copy()
    st.subheader("Match by match")
    m_pick = st.selectbox("Metric", [k for k in metrics if k not in ("Goals",)], index=0)
    k = metrics[m_pick]
    fig = go.Figure()
    fig.add_bar(x=L.date, y=L[f"{k}_for"], name="Barça", marker_color=BLAU)
    fig.add_bar(x=L.date, y=-L[f"{k}_against"], name="Opponent", marker_color=GRANA)
    fig.update_traces(customdata=L[["opponent", "venue", "score"]],
                      hovertemplate="%{x|%d %b %Y} %{customdata[1]} vs %{customdata[0]} %{customdata[2]}"
                                    "<br>%{y}<extra></extra>")
    fig.update_layout(barmode="relative", height=360, title=f"{m_pick}: Barça (up) vs opponent (down)")
    st.plotly_chart(fig, use_container_width=True)

    X = L.dropna(subset=["xg_for"])
    if len(X):
        st.subheader("xG vs goals (2026/27)")
        fig = go.Figure()
        n = np.arange(1, len(X) + 1)
        fig.add_scatter(x=n, y=X.xg_for.cumsum(), name="xG for", line=dict(color=BLAU, dash="dot"))
        fig.add_scatter(x=n, y=X.gf.cumsum(), name="Goals for", line=dict(color=BLAU, width=3))
        fig.add_scatter(x=n, y=X.xg_against.cumsum(), name="xG against", line=dict(color=GRANA, dash="dot"))
        fig.add_scatter(x=n, y=X.ga.cumsum(), name="Goals against", line=dict(color=GRANA, width=3))
        fig.update_layout(height=360, xaxis_title="League game", yaxis_title="Cumulative")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Across {len(X)} games: {X.gf.sum()} goals from {X.xg_for.sum():.1f} xG; conceded "
                   f"{X.ga.sum()} from {X.xg_against.sum():.1f} xG against. football-data.co.uk does not "
                   "document which xG model it uses.")

# ================================================================== Europe & cups
with tabs[4]:
    for comp in ["Champions League", "Copa del Rey", "Supercopa de España"]:
        C = M[(M.competition == comp) & M.season.isin(seasons)].sort_values("date")
        st.subheader(comp)
        if C.empty:
            st.info("No matches in the data for the selected seasons.")
            continue
        for s, g in C.groupby("season"):
            r = record(g)
            st.markdown(f"**{s}**: {r['P']} games, {r['W']}-{r['D']}-{r['L']}, goals {r['GF']}:{r['GA']}")
            # two-legged ties: aggregate by round + opponent
            ko = g[~g["round"].str.startswith("League", na=False)]
            ties = ko.groupby(["round", "opponent"], sort=False).agg(
                legs=("gf", "size"), GF=("gf", "sum"), GA=("ga", "sum"),
                scores=("score", " / ".join), note=("note", lambda x: " ".join(n for n in x if n))).reset_index()
            ties["Through?"] = np.where(ties.GF > ties.GA, "✓",
                                        np.where(ties.GF < ties.GA, "✗", "level (see note)"))
            lp = g[g["round"].str.startswith("League", na=False)]
            cc1, cc2 = st.columns([2, 3])
            with cc1:
                if len(lp):
                    fig = px.bar(lp, x="round", y=lp.gf - lp.ga, color="result", color_discrete_map=RESULT_COLORS,
                                 hover_data=["opponent", "venue", "score"], text="score",
                                 title=f"League phase {s}")
                    fig.update_layout(xaxis_title=None, yaxis_title="Goal difference", height=320,
                                      xaxis_tickangle=-40, showlegend=False)
                    fig.update_xaxes(ticktext=[x.split(",")[-1].strip() for x in lp["round"]],
                                     tickvals=list(lp["round"]))
                    st.plotly_chart(fig, use_container_width=True)
            with cc2:
                if len(ties):
                    st.dataframe(ties.rename(columns={"round": "Round", "opponent": "Opponent", "legs": "Legs",
                                                      "scores": "Scores", "note": "Note"}),
                                 hide_index=True, use_container_width=True)
    UCL = M[(M.competition == "Champions League") & M.season.isin(seasons)]
    if len(UCL):
        st.subheader("Champions League record by opponent's country")
        cr = UCL.groupby("opp_country").apply(lambda g: pd.Series(record(g)), include_groups=False).reset_index()
        st.dataframe(cr[["opp_country", "P", "W", "D", "L", "GF", "GA", "Win %"]].sort_values("P", ascending=False),
                     hide_index=True, use_container_width=True, column_config={"Win %": PCT})

# ================================================================== Players
with tabs[5]:
    det = D["detail"]
    st.caption("La Liga 2025/26 only: the one competition-season with line-ups and scorers in a free source "
               "reachable here. Minutes are approximate (every match counted as 90', stoppage time ignored). "
               "No assist data.")
    if det is None:
        st.warning("Detailed file not available.")
    else:
        A, Gl, Cd, Mt = det["apps"], det["goals"], det["cards"], det["matches"]
        bg = Gl[(Gl.side == "for") & ~Gl.own_goal]
        p = A.groupby("player").agg(Apps=("player", "size"), Starts=("start", "sum"),
                                    Minutes=("minutes", "sum"), Captain=("captain", "sum"))
        p["Sub apps"] = p.Apps - p.Starts
        p["Goals"] = bg.groupby("player").size()
        p["Pens"] = bg[bg.penalty].groupby("player").size()
        p["Yellow"] = Cd[Cd.card == "Yellow"].groupby("player").size()
        p["Red"] = Cd[Cd.card.isin(["Red", "Yellow-Red"])].groupby("player").size()
        p = p.fillna(0)
        p["Goals/90"] = 90 * p.Goals / p.Minutes.replace(0, np.nan)
        p["Mins/goal"] = p.Minutes / p.Goals.replace(0, np.nan)
        p["% of team mins"] = 100 * p.Minutes / (90 * len(Mt))
        p = p.sort_values(["Goals", "Minutes"], ascending=False).reset_index()
        for c in ["Apps", "Starts", "Minutes", "Captain", "Sub apps", "Goals", "Pens", "Yellow", "Red"]:
            p[c] = p[c].astype(int)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Players used", len(p))
        k2.metric("Different scorers", int((p.Goals > 0).sum()))
        k3.metric("Own goals in Barça's favour", int(((Gl.side == "for") & Gl.own_goal).sum()))
        k4.metric("Penalties scored", int(bg.penalty.sum()))
        st.dataframe(p[["player", "Apps", "Starts", "Sub apps", "Minutes", "% of team mins", "Goals", "Pens",
                        "Goals/90", "Mins/goal", "Yellow", "Red", "Captain"]],
                     hide_index=True, use_container_width=True, height=420,
                     column_config={"Goals/90": F2, "Mins/goal": st.column_config.NumberColumn(format="%.0f"),
                                    "% of team mins": PCT})

        c1, c2 = st.columns(2)
        with c1:
            top = p[p.Goals > 0].sort_values("Goals")
            fig = go.Figure()
            fig.add_bar(y=top.player, x=top.Goals - top.Pens, orientation="h", name="Open play / other",
                        marker_color=BLAU)
            fig.add_bar(y=top.player, x=top.Pens, orientation="h", name="Penalties", marker_color=GOLD)
            fig.update_layout(barmode="stack", title="Goals", height=40 + 24 * len(top))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            mm = p.sort_values("Minutes").tail(25)
            fig = go.Figure()
            fig.add_bar(y=mm.player, x=mm.Starts, orientation="h", name="Starts", marker_color=BLAU)
            fig.add_bar(y=mm.player, x=mm["Sub apps"], orientation="h", name="Sub apps", marker_color="#9AA5B1")
            fig.update_layout(barmode="stack", title="Appearances (top 25 by minutes)", height=40 + 24 * len(mm))
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("When goals happen")
        Gl2 = Gl.copy()
        Gl2["bucket"] = pd.cut(Gl2.minute.clip(upper=90.99), bins=[0, 15, 30, 45.99, 60, 75, 91],
                               labels=["1-15", "16-30", "31-45+", "46-60", "61-75", "76-90+"], include_lowest=True)
        tb = Gl2.groupby(["bucket", "side"], observed=False).size().reset_index(name="goals")
        tb["side"] = tb.side.map({"for": "Scored", "against": "Conceded"})
        fig = px.bar(tb, x="bucket", y="goals", color="side", barmode="group", text="goals",
                     color_discrete_map={"Scored": BLAU, "Conceded": GRANA})
        fig.update_layout(xaxis_title="Minute", height=340)
        st.plotly_chart(fig, use_container_width=True)

        # game states from goal sequence
        rows = []
        for _, m in Mt.iterrows():
            ev = Gl[Gl.date == m.date].sort_values("minute")
            f = a = 0
            led = trailed = False
            first = None
            for _, e in ev.iterrows():
                if e.side == "for":
                    f += 1
                else:
                    a += 1
                first = first or e.side
                led |= f > a
                trailed |= a > f
            res = "W" if m.gf > m.ga else ("L" if m.gf < m.ga else "D")
            rows.append({"date": m.date, "opponent": m.opponent, "first": first, "led": led, "trailed": trailed,
                         "result": res, "pts": {"W": 3, "D": 1, "L": 0}[res]})
        GS = pd.DataFrame(rows)
        c1, c2, c3 = st.columns(3)
        sf, cf = GS[GS["first"] == "for"], GS[GS["first"] == "against"]
        c1.metric("Scored first", f"{len(sf)} games", f"{sf.pts.mean():.2f} pts/game" if len(sf) else None,
                  delta_color="off")
        c2.metric("Conceded first", f"{len(cf)} games", f"{cf.pts.mean():.2f} pts/game" if len(cf) else None,
                  delta_color="off")
        comeback = GS[GS.trailed]
        c3.metric("Points won from losing positions", int(comeback.pts.sum()),
                  f"in {len(comeback)} games where Barça trailed", delta_color="off")
        lost_lead = GS[GS.led & (GS.result != "W")]
        st.caption(f"Points dropped from winning positions: {int((3 - lost_lead.pts).sum())} "
                   f"({len(lost_lead)} games). Order of goals in the same minute of stoppage time may be imprecise.")

        st.subheader("Who scored against Barça")
        ag = Gl[(Gl.side == "against") & ~Gl.own_goal].groupby("player").size().sort_values(ascending=False)
        st.write(", ".join(f"{n} ({c})" for n, c in ag.head(12).items()))

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Referees")
            Mt2 = Mt.copy()
            Mt2["result"] = np.where(Mt2.gf > Mt2.ga, "W", np.where(Mt2.gf < Mt2.ga, "L", "D"))
            ref = Mt2.groupby("referee").agg(Games=("result", "size"), W=("result", lambda x: (x == "W").sum()),
                                             D=("result", lambda x: (x == "D").sum()),
                                             L=("result", lambda x: (x == "L").sum()))
            cards_by = Cd.merge(Mt2[["date", "referee"]], on="date").groupby("referee").size()
            ref["Barça cards"] = cards_by
            st.dataframe(ref.fillna(0).astype(int).sort_values("Games", ascending=False), use_container_width=True)
        with c2:
            st.subheader("Home venue & attendance")
            hm = Mt[Mt.venue == "Home"].sort_values("date")
            fig = px.bar(hm, x="date", y="attendance", color="stadium", hover_data=["opponent"],
                         title="League home games, 2025/26")
            fig.update_layout(height=360, legend=dict(orientation="h", y=-0.3))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Attendance as recorded in openfootball; not verified against official figures.")

# ================================================================== Opponents
with tabs[6]:
    g = F.copy()
    g["col"] = g.season + " · " + g.competition.str.replace("Champions League", "UCL").str.replace("Copa del Rey", "Copa")
    g["label"] = g.venue.str[0] + " " + g.score
    piv = g.pivot_table(index="opponent", columns="col", values="label", aggfunc=" / ".join)
    pts = g.assign(p=g.result.map({"W": 3, "D": 1, "L": 0})).pivot_table(index="opponent", columns="col",
                                                                        values="p", aggfunc="mean")
    order = g.groupby("opponent").size().sort_values(ascending=False).index
    piv, pts = piv.reindex(order), pts.reindex(index=order, columns=piv.columns)
    fig = go.Figure(go.Heatmap(z=pts.values, x=list(piv.columns), y=list(piv.index),
                               text=piv.fillna("").values, texttemplate="%{text}", hoverongaps=False,
                               colorscale=[[0, RESULT_COLORS["L"]], [1 / 3, RESULT_COLORS["D"]], [1, RESULT_COLORS["W"]]],
                               zmin=0, zmax=3, showscale=False, xgap=2, ygap=2))
    fig.update_layout(height=60 + 24 * len(piv), yaxis=dict(autorange="reversed"), xaxis_side="top",
                      margin=dict(l=10, r=10, t=60, b=10))
    st.caption("Ordered by number of meetings. Colour = average result in that column (green win, red loss). "
               "Note: team names differ slightly between sources (e.g. 'Real Madrid' vs 'Real Madrid CF').")
    st.plotly_chart(fig, use_container_width=True)
    opp = g.groupby("opponent").apply(lambda x: pd.Series(record(x)), include_groups=False).reset_index()
    st.dataframe(opp.sort_values("P", ascending=False)[["opponent", "P", "W", "D", "L", "GF", "GA", "GD", "Win %"]],
                 hide_index=True, use_container_width=True, column_config={"Win %": PCT})

# ================================================================== Match log
with tabs[7]:
    cols = ["date", "season", "competition", "round", "venue", "opponent", "score", "result", "note",
            "shots_for", "shots_against", "sot_for", "sot_against", "corners_for", "corners_against",
            "xg_for", "xg_against", "p_win"]
    log = F[cols].sort_values("date", ascending=False).reset_index(drop=True)
    log["p_win"] = 100 * log.p_win
    st.dataframe(log.style.apply(lambda r: [f"color:{RESULT_COLORS[r.result]};font-weight:600" if c == "result"
                                            else "" for c in r.index], axis=1),
                 hide_index=True, use_container_width=True, height=600,
                 column_config={"date": st.column_config.DateColumn(format="DD MMM YYYY"),
                                "p_win": st.column_config.NumberColumn("Market P(win)", format="%.0f%%"),
                                "xg_for": F2, "xg_against": F2})
    st.download_button("Download CSV", log.to_csv(index=False), "barca_flick_matches.csv", "text/csv")

# ================================================================== Possession flow
FLOW_DIR = Path(__file__).with_name("flow")


@st.cache_data(show_spinner=False)
def flow_page() -> str:
    html = (FLOW_DIR / "flow.html").read_text(encoding="utf-8")
    return html.replace("/*__FLOW_DATA__*/null", (FLOW_DIR / "flow_data.json").read_text(encoding="utf-8"))


with tabs[8]:
    st.markdown("**How Barça moved the ball under each coach**: every pass and carry of a season laid on one "
                "pitch, drawn like a wind map. Thick, bright channels are the routes used most; colour and "
                "particle speed show how fast the ball travelled there.")
    st.caption("Event data with pass and carry locations is not freely available for the Flick years, so this uses "
               "StatsBomb's open data: La Liga matches from 2007/08–2020/21 (the matches StatsBomb released, not "
               "every game of each season). The sidebar filters don't apply here. Built from the "
               "[possession-flow blueprint](https://github.com/opengoalapp/football-blueprints/tree/main/possession-flow).")
    components.html(flow_page(), height=760, scrolling=True)

# ================================================================== Data & coverage
with tabs[9]:
    st.subheader("What's in the data")
    st.dataframe(D["coverage"], hide_index=True, use_container_width=True)
    st.subheader("Where each file came from on this load")
    st.dataframe(D["fetch_log"], hide_index=True, use_container_width=True,
                 column_config={"url": st.column_config.LinkColumn("Source file")})
    st.caption("live = downloaded now · snapshot = copy bundled in the repo (`barca-flick/data/`), used when the "
               "live source is unreachable. Refresh it with `python barca-flick/refresh_snapshot.py`.")
    st.markdown("""
**Sources**
- **football-data.co.uk**, La Liga CSVs (`SP1.csv`): results, half-time scores, shots, shots on target,
  fouls, corners, cards, average pre-match odds. xG columns appear from 2026/27.
- **openfootball** (public domain, community maintained): Champions League 2024/25–2025/26,
  Copa del Rey 2024/25, and the detailed La Liga 2025/26 file (line-ups, substitutions, scorers, cards,
  referees, venues, attendance).
- **StatsBomb open data** (Possession flow tab only): Barça's La Liga passes and carries for one season per
  coach, 2007/08–2020/21, processed by `flow/prepare_flow.py` into `flow/flow_data.json`.
- **Wikipedia** season pages ("2024–25 FC Barcelona season" etc.), via `extra_matches.csv`: Supercopa
  2024/25 & 2025/26 and Copa del Rey 2025/26. Each row keeps the page revision and the LaLiga match-report link.
  Refresh with `python barca-flick/update_from_wikipedia.py`. Where a live source has the same match, the
  live source is used and the scores are compared.

**Checks run on load during development**
- All La Liga scores in openfootball and football-data.co.uk agree (2025/26, 2026/27).
- Wikipedia agrees with openfootball on all 12 Champions League 2025/26 and all 6 Copa del Rey 2024/25 matches.
- In the detailed 2025/26 file, parsed goals add up to the score in all 38 Barça games, and every game has 11 starters.

**Known gaps and limitations**
- No source yet for **Champions League 2026/27**, assists, or player stats outside La Liga 2025/26.
- Wikipedia is editable by anyone; its match boxes cite LaLiga's official reports, which are linked in the CSV.
- The 2026/27 season is in progress; numbers change as sources update (cached for 6 hours).
- The league table is computed (points, GD, GF), not official.
- Treat everything here as unofficial and verify important numbers with official sources.

**Adding missing matches** – edit `extra_matches.csv` next to `app.py`:
""")
    st.code("date,competition,round,opponent,venue,gf,ga,note,stadium,attendance,referee,report,source\n"
            "YYYY-MM-DD,Supercopa de España,Final,<opponent>,Neutral,<goals for>,<goals against>,,,,,,my source", language="csv")
