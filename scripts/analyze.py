"""Moteur d'analyse : transforme le cache brut (data/) en données du site (site/data/).

Calcule pour chaque joueur du soir, sur 10 stats :
  moyenne, forme, ligne, défense adverse par poste, rythme, absences (avec/sans),
  face à face, style de jeu vs profil défensif, domicile/extérieur, back-to-back.
"""
import os
import sys
import glob
import math
import datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (RAW, GAMES_DIR, LINES_DIR, SITE_DATA, STATS, LOG_FIELDS, ET,
                    now_et, season_of, season_label, pos_bucket, stat_value,
                    load_json, save_json, norm_name)

BUCKET_FR = {"G": "meneurs/arrières", "F": "ailiers", "C": "pivots"}
BUCKET_SHORT = {"G": "Arrière", "F": "Ailier", "C": "Pivot"}
STAT_KEYS = list(STATS.keys())
MIN_GAMES_WITHOUT = 8   # matchs sans le coéquipier requis pour afficher une flèche « Absences »
OUT_STATUSES = {"out", "doubtful", "suspension", "suspended"}


SINGULAR = {"Heat", "Jazz", "Magic", "Thunder"}


def aux(short):
    return f"au {short}" if short in SINGULAR else f"aux {short}"


def Les(short):
    x = les(short)
    return x[0].upper() + x[1:]


def les(short):
    """Article français : « les Warriors », « le Heat »."""
    return f"le {short}" if short in SINGULAR else f"les {short}"


def r1(x):
    return None if x is None else round(x, 1)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


# ======================================================================= chargement
def load_games():
    games = []
    for path in glob.glob(os.path.join(GAMES_DIR, "*", "*.json")):
        g = load_json(path)
        if g and g.get("date") and g.get("players"):
            games.append(g)
    games.sort(key=lambda g: (g["date"], g["id"]))
    return games


def load_lines():
    hist = {}
    for path in glob.glob(os.path.join(LINES_DIR, "*.json")):
        day = os.path.basename(path)[:-5]
        hist[day] = load_json(path, {})
    return hist


# ======================================================================= construction
def build(games):
    logs = defaultdict(list)          # pid -> lignes de match
    info = {}                         # pid -> dernières infos connues
    team_games = defaultdict(list)    # équipe -> matchs (rythme, présences)
    for g in games:
        h, a = g["home"]["abbr"], g["away"]["abbr"]
        side = {h: {"opp": a, "home": 1}, a: {"opp": h, "home": 0}}
        agg = {t: defaultdict(float) for t in (h, a)}
        present = {h: set(), a: set()}
        rosters = {h: set(), a: set()}
        for p in g["players"]:
            t = p["team"]
            if t not in side:
                continue
            rosters[t].add(p["id"])
            info[p["id"]] = {"name": p["name"], "pos": p.get("pos") or info.get(p["id"], {}).get("pos", ""),
                             "team": t, "last": g["date"], "season": g["season"]}
            if p.get("dnp") or not p.get("min"):
                continue
            present[t].add(p["id"])
            for k in ("min", "pts", "fga", "fta", "oreb", "tov", "tpm", "tpa", "reb", "ast"):
                agg[t][k] += p.get(k, 0) or 0
            row = {f: p.get(f, 0) for f in LOG_FIELDS}
            row.update({"date": g["date"], "season": g["season"], "opp": side[t]["opp"],
                        "home": side[t]["home"], "team": t, "event": g["id"],
                        "starter": p.get("starter", 0), "bucket": pos_bucket(p.get("pos"))})
            logs[p["id"]].append(row)
        for t in (h, a):
            o = side[t]["opp"]
            poss = agg[t]["fga"] + 0.44 * agg[t]["fta"] - agg[t]["oreb"] + agg[t]["tov"]
            opp_poss = agg[o]["fga"] + 0.44 * agg[o]["fta"] - agg[o]["oreb"] + agg[o]["tov"]
            gmin = max(agg[t]["min"] / 5, 48) if agg[t]["min"] else 48
            pace = (poss + opp_poss) / 2 * 48 / gmin
            team_games[t].append({
                "date": g["date"], "season": g["season"], "opp": o, "home": side[t]["home"],
                "id": g["id"], "pace": pace, "poss": poss, "opp_poss": opp_poss,
                "pts_for": agg[t]["pts"], "pts_against": agg[o]["pts"],
                "present": present[t], "roster": rosters[t],
            })
    return logs, info, team_games


def season_weights(team_games, cur):
    """Poids des matchs : saison en cours = 1 ; saison passée pondérée tant que
    la saison en cours compte peu de matchs (début de saison)."""
    w = {}
    for t, lst in team_games.items():
        n_cur = sum(1 for x in lst if x["season"] == cur)
        w_prev = max(0.0, 1 - n_cur / 20) * 0.6
        w[t] = {cur: 1.0, cur - 1: w_prev}
    return w


# ======================================================================= défense par poste
def compute_dvp(games, cur, weights):
    acc = defaultdict(lambda: defaultdict(float))   # (def_team, bucket) -> sommes
    gcount = defaultdict(float)                      # def_team -> nb matchs pondéré
    for g in games:
        h, a = g["home"]["abbr"], g["away"]["abbr"]
        opp_of = {h: a, a: h}
        for d in (h, a):
            w = weights.get(d, {}).get(g["season"], 0)
            if not w:
                continue
            gcount[d] += w
            for p in g["players"]:
                if p["team"] != opp_of[d] or p.get("dnp") or not p.get("min"):
                    continue
                b = pos_bucket(p.get("pos"))
                A = acc[(d, b)]
                A["min"] += w * p["min"]
                for s in STAT_KEYS:
                    A[s] += w * stat_value(p, s)
    teams = sorted({d for d, _ in acc})
    out = {t: {} for t in teams}
    league = {}
    for b in "GFC":
        tot_min = sum(acc[(t, b)]["min"] for t in teams) or 1
        league[b] = {}
        for s in STAT_KEYS:
            l36 = sum(acc[(t, b)][s] for t in teams) / tot_min * 36
            lpg = sum(acc[(t, b)][s] for t in teams) / (sum(gcount[t] for t in teams) or 1)
            league[b][s] = [round(lpg, 1), l36]
        for s in STAT_KEYS:
            rows = []
            for t in teams:
                A = acc[(t, b)]
                pg = A[s] / gcount[t] if gcount[t] else 0
                p36 = A[s] / A["min"] * 36 if A["min"] else 0
                ratio = p36 / league[b][s][1] if league[b][s][1] else 1
                rows.append((t, pg, ratio))
            rows.sort(key=lambda x: -x[2])          # rang 1 = la plus généreuse
            for rank, (t, pg, ratio) in enumerate(rows, 1):
                out[t].setdefault(b, {})[s] = [round(pg, 1), rank, round(ratio, 3)]
    return out, {b: {s: v[0] for s, v in league[b].items()} for b in league}


def team_profiles(dvp, team_games, cur, weights):
    """Profil défensif de chaque équipe (étiquette lisible) + rythme + note défensive."""
    stats = {}
    for t, lst in team_games.items():
        wsum = poss = against = pace = 0.0
        for x in lst:
            w = weights.get(t, {}).get(x["season"], 0)
            if not w:
                continue
            wsum += w
            poss += w * x["opp_poss"]
            against += w * x["pts_against"]
            pace += w * x["pace"]
        if wsum:
            stats[t] = {"pace": pace / wsum, "drtg": against / poss * 100 if poss else 0,
                        "gp": sum(1 for x in lst if x["season"] == cur)}
    if not stats:
        return {}
    lg_pace = mean(v["pace"] for v in stats.values())
    lg_drtg = mean(v["drtg"] for v in stats.values())
    by_pace = sorted(stats, key=lambda t: -stats[t]["pace"])
    by_drtg = sorted(stats, key=lambda t: stats[t]["drtg"])
    prof = {}
    for t, v in stats.items():
        d = dvp.get(t, {})
        inside = d.get("C", {}).get("pts", [0, 0, 1])[2]
        guards = d.get("G", {}).get("pts", [0, 0, 1])[2]
        three = mean(d.get(b, {}).get("tpm", [0, 0, 1])[2] for b in "GFC")
        drtg_r = v["drtg"] / lg_drtg if lg_drtg else 1
        cands = []
        if inside <= 0.93: cands.append(("Mur intérieur", 1 - inside))
        if three <= 0.92: cands.append(("Verrou à 3 pts", 1 - three))
        if guards <= 0.93: cands.append(("Anti-meneurs", 1 - guards))
        if drtg_r <= 0.965: cands.append(("Défense d'élite", (1 - drtg_r) * 2))
        if drtg_r >= 1.035: cands.append(("Passoire", (drtg_r - 1) * 2))
        if inside >= 1.08: cands.append(("Raquette ouverte", inside - 1))
        if three >= 1.08: cands.append(("Perméable à 3 pts", three - 1))
        if guards >= 1.08: cands.append(("Faible sur les arrières", guards - 1))
        cands.sort(key=lambda x: -x[1])
        prof[t] = {
            "profile": cands[0][0] if cands else "Équilibrée",
            "tags": [c[0] for c in cands[:3]],
            "pace": r1(v["pace"]), "pace_rank": by_pace.index(t) + 1,
            "drtg": r1(v["drtg"]), "drtg_rank": by_drtg.index(t) + 1,
            "gp": v["gp"],
        }
    prof["_league"] = {"pace": r1(lg_pace), "drtg": r1(lg_drtg)}
    return prof


# ======================================================================= styles de joueurs
def style_from_rows(rows, bucket):
    rows = [r for r in rows if r["min"] > 0]
    mins = sum(r["min"] for r in rows)
    if len(rows) < 3 or mins < 60:
        return None
    per36 = lambda k: sum(r[k] for r in rows) / mins * 36
    pts, ast, reb, tpa, fga, fta = (per36(k) for k in ("pts", "ast", "reb", "tpa", "fga", "fta"))
    blk = per36("blk")
    three_share = tpa / fga if fga else 0
    if bucket == "C":
        if tpa >= 3.5: return "Pivot stretch"
        if ast >= 5: return "Pivot passeur"
        if blk >= 2.2: return "Protecteur de cercle"
        return "Pivot intérieur"
    if pts >= 25 and three_share < 0.45: return "Iso-scoreur"
    if bucket == "G" and ast >= 7: return "Meneur P&R"
    if pts >= 25: return "Scoreur à 3 pts"
    if three_share >= 0.55 and tpa >= 5: return "Sniper"
    if bucket == "F" and ast >= 5: return "Ailier créateur"
    if bucket == "F" and reb >= 10: return "Ailier rebondeur"
    if fta >= 5 and three_share < 0.35: return "Attaquant de pénétration"
    if tpa >= 4: return "Profil 3&D"
    if bucket == "G": return "Arrière polyvalent"
    return "Ailier de rôle"


def player_bucket(rows, info_pos):
    if info_pos:
        return pos_bucket(info_pos)
    cnt = defaultdict(int)
    for r in rows[-20:]:
        cnt[r["bucket"]] += 1
    return max(cnt, key=cnt.get) if cnt else "F"


# ======================================================================= helpers stats
def avg_stat(rows, s):
    rows = [r for r in rows if r["min"] > 0]
    return mean(stat_value(r, s) for r in rows)


def default_line(avg):
    if avg is None:
        return None
    if avg < 1:
        return 0.5
    return math.floor(avg) + 0.5


def with_without(pid, team, mates, logs, team_games, seasons, info):
    """Moyennes du joueur avec / sans chacun des coéquipiers absents ce soir."""
    my = {r["event"]: r for r in logs.get(pid, []) if r["team"] == team and r["season"] in seasons}
    out = []
    for m in mates:
        mid = m["id"]
        if mid == pid or mid not in logs:
            continue
        ranges = {}
        for r in logs[mid]:
            if r["team"] == team and r["season"] in seasons:
                lo, hi = ranges.get(r["season"], (r["date"], r["date"]))
                ranges[r["season"]] = (min(lo, r["date"]), max(hi, r["date"]))
        if not ranges:
            continue
        still_here = info.get(mid, {}).get("team") == team
        w, wo = [], []
        for tg in team_games.get(team, []):
            rg = ranges.get(tg["season"])
            if not rg or tg["id"] not in my:
                continue
            hi = "9999" if (still_here and tg["season"] == max(ranges)) else rg[1]
            if not (rg[0] <= tg["date"] <= hi):
                continue
            (w if mid in tg["present"] else wo).append(my[tg["id"]])
        if len(wo) < 2 or not w:
            continue
        out.append({
            "id": mid, "name": m["name"], "status": m["status"],
            "n_with": len(w), "n_wo": len(wo),
            "with": {s: r1(avg_stat(w, s)) for s in STAT_KEYS} | {k: r1(mean(r[k] for r in w)) for k in ("min", "fga", "tpa", "fta")},
            "wo": {s: r1(avg_stat(wo, s)) for s in STAT_KEYS} | {k: r1(mean(r[k] for r in wo)) for k in ("min", "fga", "tpa", "fta")},
        })
    return out


# ======================================================================= main
def main():
    games = load_games()
    if not games:
        print("Aucun match en cache : lance d'abord scripts/fetch.py")
        return
    sched = load_json(os.path.join(RAW, "schedule.json"), {"days": []})
    injuries = load_json(os.path.join(RAW, "injuries.json"), {})
    teams_meta = load_json(os.path.join(RAW, "teams.json"), {})
    lines_hist = load_lines()

    # Choix de la soirée : premier jour avec des matchs non terminés, sinon le dernier
    day = None
    for d in sched.get("days", []):
        day = d
        if any(g["state"] != "post" for g in d["games"]):
            break
    tonight = day["games"] if day else []
    date = day["date"] if day else now_et().date().isoformat()
    cur = season_of(dt.date.fromisoformat(date))
    if not any(g["season"] == cur for g in games):
        cur = max(g["season"] for g in games)

    logs, info, team_games = build(games)
    weights = season_weights(team_games, cur)
    dvp, dvp_league = compute_dvp(games, cur, weights)
    prof = team_profiles(dvp, team_games, cur, weights)
    lg_pace = prof.get("_league", {}).get("pace") or 100

    # styles par saison de chaque joueur
    style_season = {}
    for pid, rows in logs.items():
        b = player_bucket(rows, info[pid]["pos"])
        by_s = defaultdict(list)
        for r in rows:
            by_s[r["season"]].append(r)
        for s, rr in by_s.items():
            style_season[(pid, s)] = style_from_rows(rr, b)

    # agrégat : joueurs d'un style donné face à chaque équipe (vs leur moyenne de saison)
    season_avg = {}
    for pid, rows in logs.items():
        by_s = defaultdict(list)
        for r in rows:
            by_s[r["season"]].append(r)
        for s, rr in by_s.items():
            season_avg[(pid, s)] = {k: avg_stat(rr, k) for k in STAT_KEYS}
    style_vs_team = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    for pid, rows in logs.items():
        for r in rows:
            sty = style_season.get((pid, r["season"]))
            if not sty or r["min"] < 12:
                continue
            A = style_vs_team[(sty, r["opp"])]
            av = season_avg[(pid, r["season"])]
            for k in STAT_KEYS:
                if av[k] is None:
                    continue
                v = stat_value(r, k)
                A[k][0] += 1
                A[k][1] += v > av[k]
                if r["season"] == cur:
                    A[k][2] += 1
                    A[k][3] += v > av[k]

    # back-to-back : l'équipe a-t-elle joué la veille ?
    yday = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    played_yday = {t for t, lst in team_games.items() if any(x["date"] == yday for x in lst)}

    # blessures indexées
    inj_by_team = {t: v for t, v in injuries.items() if not t.startswith("_")}
    inj_by_id, inj_by_name = {}, {}
    for t, lst in inj_by_team.items():
        for i in lst:
            if i.get("id"):
                inj_by_id[i["id"]] = i
            inj_by_name[(t, norm_name(i["name"]))] = i

    def injury_of(pid, team):
        return inj_by_id.get(pid) or inj_by_name.get((team, norm_name(info[pid]["name"])))

    today_lines = lines_hist.get(date, {})
    os.makedirs(os.path.join(SITE_DATA, "p"), exist_ok=True)
    for old in glob.glob(os.path.join(SITE_DATA, "p", "*.json")):
        os.remove(old)

    tonight_teams = {}
    for g in tonight:
        tonight_teams[g["home"]] = (g["away"], 1, g)
        tonight_teams[g["away"]] = (g["home"], 0, g)

    # effectifs : joueurs dont la dernière équipe connue joue ce soir
    roster = defaultdict(list)
    recent_season = {cur, cur - 1}
    for pid, i in info.items():
        if i["team"] in tonight_teams and i["season"] in recent_season:
            cur_rows = [r for r in logs.get(pid, []) if r["season"] == cur and r["min"] > 0]
            if i["season"] == cur and cur_rows:
                roster[i["team"]].append(pid)
            elif i["season"] == cur - 1 and not any(g["season"] == cur for g in games[-50:]):
                roster[i["team"]].append(pid)

    # absents (OUT / douteux) par équipe, enrichis de l'id quand on le retrouve
    absent = defaultdict(list)
    name_to_pid = {(i["team"], norm_name(i["name"])): pid for pid, i in info.items()}
    for t in tonight_teams:
        for inj in inj_by_team.get(t, []):
            if (inj.get("status") or "").lower() not in OUT_STATUSES:
                continue
            pid = inj.get("id") if inj.get("id") in info else name_to_pid.get((t, norm_name(inj["name"])))
            absent[t].append({"id": pid, "name": inj["name"], "status": inj["status"],
                              "comment": inj.get("comment", "")})

    players_out = []
    relief = defaultdict(list)   # équipe -> qui prend le relais
    n_files = 0
    for team, pids in roster.items():
        opp, home, g = tonight_teams[team]
        op = prof.get(opp, {})
        mp = prof.get(team, {})
        proj_pace = mean([x for x in (op.get("pace"), mp.get("pace")) if x]) or lg_pace
        pace_diff = proj_pace - lg_pace
        mates_out = [m for m in absent.get(team, []) if m["id"]]
        for pid in pids:
            i = info[pid]
            rows = logs[pid]
            played = [r for r in rows if r["min"] > 0]
            cur_rows = [r for r in played if r["season"] == cur]
            base_rows = cur_rows if len(cur_rows) >= 3 else [r for r in played if r["season"] >= cur - 1][-20:]
            if not base_rows:
                continue
            mpg = mean(r["min"] for r in base_rows)
            if mpg < 8 and len(cur_rows) < 3:
                continue
            bucket = player_bucket(rows, i["pos"])
            style = (style_season.get((pid, cur)) if len(cur_rows) >= 5 else None) \
                or style_season.get((pid, cur - 1)) or style_from_rows(played[-30:], bucket) \
                or ("Pivot intérieur" if bucket == "C" else "Joueur de rotation")
            inj = injury_of(pid, team)
            status = inj.get("status") if inj else None
            l5, l10 = played[-5:], played[-10:]
            l5min = mean(r["min"] for r in l5)
            venue_rows = [r for r in played if r["season"] >= cur - 1 and r["home"] == home]
            h2h_rows = [r for r in played if r["opp"] == opp]
            opp_profile = op.get("profile")
            style_rows = [r for r in played if r["season"] >= cur - 1
                          and prof.get(r["opp"], {}).get("profile") == opp_profile]
            ww = with_without(pid, team, mates_out, logs, team_games, {cur, cur - 1}, info)
            name_key = norm_name(i["name"])

            s_out, factors = {}, {}
            for s in STAT_KEYS:
                A = avg_stat(base_rows, s)
                if A is None:
                    continue
                a5, a10 = avg_stat(l5, s), avg_stat(l10, s)
                book = today_lines.get(name_key, {}).get(s)
                line = book if book is not None else default_line(A)
                F = []

                def add(sign, txt, code):
                    F.append([sign, txt, code])

                # 1. défense adverse sur son poste
                dv = dvp.get(opp, {}).get(bucket, {}).get(s)
                if dv:
                    pg, rank, ratio = dv
                    pct = round((ratio - 1) * 100)
                    lab = STATS[s][0].lower()
                    if rank <= 6:
                        add(1, f"{Les(teams_meta.get(opp, {}).get('short', opp))} concèdent beaucoup aux {BUCKET_FR[bucket]} en {lab} : {pg} par match, rang {rank}/30 ({pct:+d} % vs moyenne).", "DEF")
                    elif rank >= 25:
                        add(-1, f"{Les(teams_meta.get(opp, {}).get('short', opp))} verrouillent les {BUCKET_FR[bucket]} en {lab} : {pg} par match, rang {rank}/30 ({pct:+d} %).", "DEF")
                # 2. rythme
                if s not in ("blk", "stl"):
                    if pace_diff >= 2:
                        add(1, f"Match rapide attendu : environ {proj_pace:.1f} possessions contre {lg_pace:.1f} en moyenne, plus de ballons à jouer.", "PACE")
                    elif pace_diff <= -2:
                        add(-1, f"Match lent attendu : environ {proj_pace:.1f} possessions contre {lg_pace:.1f} en moyenne.", "PACE")
                # 3. forme
                if len(played) >= 5 and A and a5 is not None:
                    rel = (a5 - A) / A if A else 0
                    if rel >= 0.15 and a5 - A >= 0.8:
                        add(1, f"En forme : {a5:.1f} sur ses 5 derniers matchs, contre {A:.1f} de moyenne.", "FORM")
                    elif rel <= -0.15 and A - a5 >= 0.8:
                        add(-1, f"Dans le dur : {a5:.1f} sur ses 5 derniers matchs, contre {A:.1f} de moyenne.", "FORM")
                # 4. temps de jeu
                if l5min is not None and mpg:
                    if l5min - mpg >= 3:
                        add(1, f"Temps de jeu en hausse : {l5min:.1f} min sur 5 matchs contre {mpg:.1f}.", "MIN")
                    elif mpg - l5min >= 3:
                        add(-1, f"Temps de jeu en baisse : {l5min:.1f} min sur 5 matchs contre {mpg:.1f}.", "MIN")
                # 5. absences
                for m in ww:
                    if m["wo"].get(s) is None or m["with"].get(s) is None or m["n_wo"] < MIN_GAMES_WITHOUT:
                        continue
                    delta = m["wo"][s] - m["with"][s]
                    if delta >= max(1.0, 0.1 * A):
                        add(1, f"{m['name']} est {m['status'].lower()} : sans lui, {m['wo'][s]} de moyenne ({m['n_wo']} matchs) contre {m['with'][s]} avec lui.", "ABS")
                    elif delta <= -max(1.0, 0.1 * A):
                        add(-1, f"{m['name']} est {m['status'].lower()} : sans lui, seulement {m['wo'][s]} ({m['n_wo']} matchs) contre {m['with'][s]}.", "ABS")
                # 6. face à face
                if len(h2h_rows) >= 3:
                    h = avg_stat(h2h_rows, s)
                    if A and h is not None:
                        rel = (h - A) / A
                        if rel >= 0.15 and h - A >= 0.8:
                            add(1, f"Lui réussit face {aux(teams_meta.get(opp, {}).get('short', opp))} : {h:.1f} de moyenne sur {len(h2h_rows)} matchs.", "H2H")
                        elif rel <= -0.15 and A - h >= 0.8:
                            add(-1, f"Souvent en difficulté face {aux(teams_meta.get(opp, {}).get('short', opp))} : {h:.1f} sur {len(h2h_rows)} matchs.", "H2H")
                # 7. domicile / extérieur
                if len(venue_rows) >= 6:
                    v = avg_stat(venue_rows, s)
                    allv = avg_stat([r for r in played if r["season"] >= cur - 1], s)
                    if allv and v is not None:
                        rel = (v - allv) / allv
                        lieu = "à domicile" if home else "à l'extérieur"
                        if rel >= 0.10 and v - allv >= 0.7:
                            add(1, f"Plus productif {lieu} : {v:.1f} contre {allv:.1f} au global.", "VEN")
                        elif rel <= -0.10 and allv - v >= 0.7:
                            add(-1, f"Moins productif {lieu} : {v:.1f} contre {allv:.1f} au global.", "VEN")
                # 8. style vs style
                if len(style_rows) >= 5 and opp_profile and opp_profile != "Équilibrée":
                    v = avg_stat(style_rows, s)
                    allv = avg_stat([r for r in played if r["season"] >= cur - 1], s)
                    if allv and v is not None:
                        rel = (v - allv) / allv
                        if rel >= 0.12 and v - allv >= 0.7:
                            add(1, f"Face aux défenses « {opp_profile} » : {v:.1f} de moyenne sur {len(style_rows)} matchs.", "STY")
                        elif rel <= -0.12 and allv - v >= 0.7:
                            add(-1, f"Face aux défenses « {opp_profile} » : seulement {v:.1f} sur {len(style_rows)} matchs.", "STY")
                # 9. fatigue
                if team in played_yday:
                    add(-1, "Deuxième match en deux soirs pour son équipe (back-to-back).", "B2B")
                if opp in played_yday:
                    add(1, f"{Les(teams_meta.get(opp, {}).get('short', opp))} jouaient déjà hier soir (back-to-back).", "B2BO")

                score = sum(f[0] for f in F)
                hit10 = sum(1 for r in l10 if stat_value(r, s) > line) if line is not None else None
                s_out[s] = [r1(A), r1(a5), r1(a10), line, 1 if book is not None else 0, score,
                            sorted({f[2] + ("+" if f[0] > 0 else "-") for f in F}), hit10, len(l10)]
                factors[s] = F

            if not s_out:
                continue
            players_out.append({
                "id": pid, "n": i["name"], "t": team, "o": opp, "h": home, "g": g["id"],
                "pos": i["pos"], "b": bucket, "sty": style, "st": status,
                "min": r1(mpg), "gp": len(cur_rows), "s": s_out,
            })

            # fiche détaillée
            hist = {}
            for d, lmap in lines_hist.items():
                if name_key in lmap:
                    hist[d] = lmap[name_key]
            career = []
            by_s = defaultdict(list)
            for r in played:
                by_s[r["season"]].append(r)
            for se in sorted(by_s, reverse=True):
                rr = by_s[se]
                teamsx = sorted({r["team"] for r in rr})
                career.append({"season": season_label(se), "team": "/".join(teamsx), "gp": len(rr),
                               "min": r1(mean(r["min"] for r in rr)),
                               "style": style_season.get((pid, se)),
                               **{s: r1(avg_stat(rr, s)) for s in STAT_KEYS},
                               "fg": r1(100 * sum(r["fgm"] for r in rr) / max(1, sum(r["fga"] for r in rr))),
                               "tp": r1(100 * sum(r["tpm"] for r in rr) / max(1, sum(r["tpa"] for r in rr))),
                               "ft": r1(100 * sum(r["ftm"] for r in rr) / max(1, sum(r["fta"] for r in rr)))})
            sb = base_rows
            fga = sum(r["fga"] for r in sb) or 1
            shot = {
                "fga": r1(mean(r["fga"] for r in sb)), "tpa": r1(mean(r["tpa"] for r in sb)),
                "fta": r1(mean(r["fta"] for r in sb)),
                "two_share": r1(100 * (fga - sum(r["tpa"] for r in sb)) / fga),
                "three_share": r1(100 * sum(r["tpa"] for r in sb) / fga),
                "fg": r1(100 * sum(r["fgm"] for r in sb) / fga),
                "tp": r1(100 * sum(r["tpm"] for r in sb) / max(1, sum(r["tpa"] for r in sb))),
                "ft": r1(100 * sum(r["ftm"] for r in sb) / max(1, sum(r["fta"] for r in sb))),
                "fta_rate": r1(100 * sum(r["fta"] for r in sb) / fga),
                "opp_dvp": {s: dvp.get(opp, {}).get(bucket, {}).get(s) for s in ("tpm", "pts")},
            }
            sty_agg = style_vs_team.get((style, opp), {})
            detail = {
                "id": pid, "name": i["name"], "team": team, "opp": opp, "home": home, "pos": i["pos"],
                "bucket": bucket, "style": style, "status": status,
                "injury": inj, "opp_profile": op, "team_profile": mp,
                "pace": {"proj": r1(proj_pace), "league": r1(lg_pace), "team": mp.get("pace"),
                         "opp": op.get("pace"), "team_rank": mp.get("pace_rank"), "opp_rank": op.get("pace_rank")},
                "dvp": {b: dvp.get(opp, {}).get(b, {}) for b in "GFC"},
                "factors": factors,
                "withwo": ww,
                "same_style_vs_opp": {s: v for s, v in sty_agg.items()},
                "career": career, "shot": shot,
                "lines": hist,
                "cols": LOG_FIELDS,
                "logs": [[r[f] for f in LOG_FIELDS] for r in played],
            }
            save_json(os.path.join(SITE_DATA, "p", f"{pid}.json"), detail)
            n_files += 1

        # qui prend le relais quand un joueur est absent
        for m in mates_out:
            best = []
            for pid in pids:
                for x in with_without(pid, team, [m], logs, team_games, {cur, cur - 1}, info):
                    if x["n_wo"] >= 2 and x["wo"]["pts"] is not None and x["with"]["pts"] is not None:
                        best.append({"id": pid, "name": info[pid]["name"],
                                     "d_pts": r1(x["wo"]["pts"] - x["with"]["pts"]),
                                     "d_min": r1((x["wo"]["min"] or 0) - (x["with"]["min"] or 0)),
                                     "n_wo": x["n_wo"]})
            best.sort(key=lambda x: -(x["d_pts"] or 0))
            relief[team].append({"name": m["name"], "status": m["status"], "comment": m["comment"],
                                 "relief": [b for b in best if (b["d_pts"] or 0) > 0][:3]})

    # ------------------------------------------------------------ sorties
    games_out = []
    for g in tonight:
        h, a = g["home"], g["away"]
        ph, pa = prof.get(h, {}).get("pace"), prof.get(a, {}).get("pace")
        games_out.append({**g, "pace": r1(mean([x for x in (ph, pa) if x]) if (ph or pa) else None),
                          "b2b": [t for t in (h, a) if t in played_yday]})
    teams_out = {}
    for t, m in teams_meta.items():
        teams_out[t] = {"name": m.get("name"), "short": m.get("short"), "color": m.get("color"),
                        "logo": m.get("logo"), **{k: v for k, v in prof.get(t, {}).items()}}
    injuries_out = {}
    for t in tonight_teams:
        injuries_out[t] = [{"name": x["name"], "status": x["status"], "comment": x.get("comment", ""),
                            "type": x.get("type")} for x in inj_by_team.get(t, [])]
    today = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "date": date, "season": season_label(cur),
        "n_games_db": len(games),
        "stats": {k: v[0] for k, v in STATS.items()},
        "games": games_out, "teams": teams_out, "players": players_out,
        "injuries": injuries_out, "injuries_updated": injuries.get("_updated"),
        "relief": relief, "league_pace": lg_pace,
        "has_book_lines": bool(today_lines),
    }
    save_json(os.path.join(SITE_DATA, "today.json"), today)
    save_json(os.path.join(SITE_DATA, "dvp.json"), {
        "season": season_label(cur), "dvp": dvp, "league": dvp_league,
        "profiles": {t: v for t, v in prof.items() if not t.startswith("_")},
        "teams": {t: {"short": m.get("short"), "name": m.get("name"), "logo": m.get("logo")} for t, m in teams_meta.items()},
        "stats": {k: v[0] for k, v in STATS.items()},
    })
    print(f"Soirée du {date} : {len(tonight)} matchs, {len(players_out)} joueurs, {n_files} fiches, "
          f"{sum(len(v) for v in absent.values())} absents")


if __name__ == "__main__":
    main()
