"""Collecte des données gratuites : calendrier, box scores, blessures (ESPN),
et en option les lignes bookmakers (The Odds API, clé gratuite).

Tout est mis en cache dans data/ : seuls les nouveaux matchs sont téléchargés.
Variables d'environnement :
  HISTORY_SEASONS  nombre de saisons passées à garder pour le H2H (défaut 2)
  ODDS_API_KEY     clé The Odds API (facultatif)
  ODDS_MARKETS     marchés à récupérer (défaut : player_points)
  MAX_NEW_GAMES    plafond de box scores téléchargés par exécution (défaut 6000)
"""
import os
import sys
import time
import json
import random
import datetime as dt
import urllib.request
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (RAW, GAMES_DIR, LINES_DIR, ET, now_et, season_of, season_bounds,
                    load_json, save_json, norm_name)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = "Mozilla/5.0 (compatible; matchup-nba-perso/1.0)"
GOOD_SEASON_TYPES = {2, 3, 5}  # saison régulière, playoffs, play-in

STATE_PATH = os.path.join(RAW, "state.json")


def get_json(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404, 422):
                raise
        except Exception as e:  # réseau, JSON tronqué…
            last = e
        time.sleep(1.5 * (i + 1) + random.random())
    raise last


# ---------------------------------------------------------------- équipes
def fetch_teams():
    data = get_json(f"{ESPN}/teams")
    teams = {}
    for t in data["sports"][0]["leagues"][0]["teams"]:
        t = t["team"]
        teams[t["abbreviation"]] = {
            "id": str(t["id"]),
            "abbr": t["abbreviation"],
            "name": t.get("displayName"),
            "short": t.get("shortDisplayName") or t.get("name"),
            "color": t.get("color"),
            "logo": (t.get("logos") or [{}])[0].get("href"),
        }
    save_json(os.path.join(RAW, "teams.json"), teams, compact=False)
    return teams


# ---------------------------------------------------------------- box scores
BOX_MAP = {  # libellé ou clé ESPN -> champ normalisé
    "MIN": "min", "minutes": "min",
    "FG": "fg", "fieldGoalsMade-fieldGoalsAttempted": "fg",
    "3PT": "tp", "threePointFieldGoalsMade-threePointFieldGoalsAttempted": "tp",
    "FT": "ft", "freeThrowsMade-freeThrowsAttempted": "ft",
    "OREB": "oreb", "offensiveRebounds": "oreb",
    "REB": "reb", "rebounds": "reb",
    "AST": "ast", "assists": "ast",
    "STL": "stl", "steals": "stl",
    "BLK": "blk", "blocks": "blk",
    "TO": "tov", "turnovers": "tov",
    "PTS": "pts", "points": "pts",
}


def _num(s):
    try:
        s = str(s).strip()
        if ":" in s:  # "32:15"
            m, sec = s.split(":")
            return round(int(m) + int(sec) / 60, 1)
        return float(s) if "." in s else int(s)
    except (ValueError, TypeError):
        return 0


def _made_att(s):
    try:
        a, b = str(s).split("-")
        return int(a), int(b)
    except ValueError:
        return 0, 0


def normalize_summary(summary, event_id):
    header = summary.get("header", {})
    comp = header["competitions"][0]
    season = header.get("season", {})
    teams = {}
    for c in comp["competitors"]:
        teams[c["homeAway"]] = {"abbr": c["team"]["abbreviation"], "id": str(c["team"]["id"]),
                                "score": _num(c.get("score"))}
    game = {
        "id": str(event_id),
        "date": None,
        "season": season.get("year"),
        "stype": season.get("type"),
        "home": teams["home"], "away": teams["away"],
        "players": [],
    }
    # date locale ET du match
    d = comp.get("date") or header.get("date")
    if d:
        utc = dt.datetime.fromisoformat(d.replace("Z", "+00:00"))
        game["date"] = utc.astimezone(ET).date().isoformat()

    for block in summary.get("boxscore", {}).get("players", []):
        abbr = block["team"]["abbreviation"]
        for st in block.get("statistics", [])[:1]:
            cols = st.get("keys") or st.get("names") or st.get("labels") or []
            if not any(c in BOX_MAP for c in cols):
                cols = st.get("labels") or st.get("names") or cols
            idx = {BOX_MAP[c]: i for i, c in enumerate(cols) if c in BOX_MAP}
            for a in st.get("athletes", []):
                ath = a.get("athlete", {})
                stats = a.get("stats") or []
                p = {
                    "id": str(ath.get("id")),
                    "name": ath.get("displayName"),
                    "pos": (ath.get("position") or {}).get("abbreviation", ""),
                    "team": abbr,
                    "starter": 1 if a.get("starter") else 0,
                }
                if a.get("didNotPlay") or not stats:
                    p["dnp"] = 1
                    p["min"] = 0
                    game["players"].append(p)
                    continue
                g = lambda k: stats[idx[k]] if k in idx and idx[k] < len(stats) else 0
                p["min"] = _num(g("min"))
                p["fgm"], p["fga"] = _made_att(g("fg"))
                p["tpm"], p["tpa"] = _made_att(g("tp"))
                p["ftm"], p["fta"] = _made_att(g("ft"))
                for k in ("oreb", "reb", "ast", "stl", "blk", "tov", "pts"):
                    p[k] = _num(g(k))
                if not p["min"] and not p["pts"] and not p["reb"]:
                    p["dnp"] = 1
                game["players"].append(p)
    return game


def scoreboard(day):
    return get_json(f"{ESPN}/scoreboard?dates={day.strftime('%Y%m%d')}&limit=100")


def sync_games(seasons, max_new):
    state = load_json(STATE_PATH, {"days_done": {}})
    done = state["days_done"]
    today = now_et().date()
    fetched = 0
    for season in seasons:
        start, end = season_bounds(season)
        end = min(end, today)
        day = start
        sdir = os.path.join(GAMES_DIR, str(season))
        os.makedirs(sdir, exist_ok=True)
        while day <= end and fetched < max_new:
            key = day.isoformat()
            if done.get(key):
                day += dt.timedelta(days=1)
                continue
            try:
                sb = scoreboard(day)
            except Exception as e:
                print(f"  ! scoreboard {key}: {e}")
                day += dt.timedelta(days=1)
                continue
            all_final = True
            for ev in sb.get("events", []):
                stype = (ev.get("season") or {}).get("type")
                status = ev["competitions"][0]["status"]["type"]
                if stype not in GOOD_SEASON_TYPES:
                    continue
                if not status.get("completed"):
                    all_final = False
                    continue
                path = os.path.join(sdir, f"{ev['id']}.json")
                if os.path.exists(path):
                    continue
                try:
                    summ = get_json(f"{ESPN}/summary?event={ev['id']}")
                    game = normalize_summary(summ, ev["id"])
                    game["season"] = game["season"] or season
                    save_json(path, game)
                    fetched += 1
                    time.sleep(0.15)
                except Exception as e:
                    print(f"  ! summary {ev['id']}: {e}")
                    all_final = False
            if all_final and day < today:
                done[key] = True
            if fetched and fetched % 100 == 0:
                print(f"  … {fetched} nouveaux matchs")
                save_json(STATE_PATH, state, compact=False)
            day += dt.timedelta(days=1)
            time.sleep(0.1)
    save_json(STATE_PATH, state, compact=False)
    print(f"Box scores : {fetched} nouveaux matchs")


# ---------------------------------------------------------------- programme du soir
def sync_schedule():
    """Matchs du jour (heure de New York). S'il n'y en a pas, les prochains jours."""
    base = now_et().date()
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(), "days": []}
    for delta in range(0, 4):
        day = base + dt.timedelta(days=delta)
        sb = scoreboard(day)
        games = []
        for ev in sb.get("events", []):
            if (ev.get("season") or {}).get("type") not in GOOD_SEASON_TYPES:
                continue
            comp = ev["competitions"][0]
            teams = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
            score = {c["homeAway"]: c.get("score") for c in comp["competitors"]}
            st = comp["status"]["type"]
            games.append({
                "id": str(ev["id"]), "start": ev.get("date"),
                "home": teams.get("home"), "away": teams.get("away"),
                "state": st.get("state"), "detail": st.get("shortDetail"),
                "score": score,
            })
        if games:
            out["days"].append({"date": day.isoformat(), "games": games})
        if games and any(g["state"] != "post" for g in games):
            break
    save_json(os.path.join(RAW, "schedule.json"), out, compact=False)
    n = sum(len(d["games"]) for d in out["days"])
    print(f"Programme : {n} matchs sur {len(out['days'])} jour(s)")


# ---------------------------------------------------------------- blessures
def sync_injuries(teams):
    by_name = {t["name"]: a for a, t in teams.items()}
    by_id = {t["id"]: a for a, t in teams.items()}
    data = get_json(f"{ESPN}/injuries")
    out = {}
    for block in data.get("injuries", []):
        abbr = by_id.get(str(block.get("id"))) or by_name.get(block.get("displayName"))
        if not abbr:
            continue
        lst = []
        for inj in block.get("injuries", []):
            ath = inj.get("athlete", {})
            pid = str(ath.get("id") or "")
            if not pid:
                for l in ath.get("links", []):
                    href = l.get("href", "")
                    if "/id/" in href:
                        pid = href.split("/id/")[1].split("/")[0]
                        break
            det = inj.get("details") or {}
            lst.append({
                "id": pid,
                "name": ath.get("displayName"),
                "pos": (ath.get("position") or {}).get("abbreviation", ""),
                "status": inj.get("status"),
                "type": det.get("type"),
                "return": det.get("returnDate"),
                "comment": inj.get("shortComment") or "",
                "date": inj.get("date"),
            })
        out[abbr] = lst
    out["_updated"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_json(os.path.join(RAW, "injuries.json"), out, compact=False)
    print(f"Blessures : {sum(len(v) for k, v in out.items() if k != '_updated')} joueurs listés")


# ---------------------------------------------------------------- lignes (facultatif)
ODDS_MARKETS = {
    "player_points": "pts", "player_rebounds": "reb", "player_assists": "ast",
    "player_threes": "tpm", "player_steals": "stl", "player_blocks": "blk",
    "player_points_rebounds": "pr", "player_points_assists": "pa",
    "player_rebounds_assists": "ra", "player_points_rebounds_assists": "pra",
}


def sync_odds():
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("Lignes : pas de clé ODDS_API_KEY, étape ignorée")
        return
    day = now_et().date().isoformat()
    path = os.path.join(LINES_DIR, f"{day}.json")
    if os.path.exists(path) and not os.environ.get("FORCE_ODDS"):
        print("Lignes : déjà récupérées aujourd'hui (quota préservé)")
        return
    markets = os.environ.get("ODDS_MARKETS", "player_points")
    base = "https://api.the-odds-api.com/v4/sports/basketball_nba"
    events = get_json(f"{base}/events?apiKey={key}")
    lines = {}
    for ev in events:
        start = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(ET)
        if start.date().isoformat() != day:
            continue
        q = urllib.parse.urlencode({"apiKey": key, "regions": "us", "markets": markets,
                                    "oddsFormat": "decimal"})
        try:
            od = get_json(f"{base}/events/{ev['id']}/odds?{q}")
        except Exception as e:
            print(f"  ! cotes {ev['id']}: {e}")
            continue
        acc = {}
        for bk in od.get("bookmakers", []):
            for m in bk.get("markets", []):
                stat = ODDS_MARKETS.get(m["key"])
                for o in m.get("outcomes", []):
                    if o.get("name") != "Over" or o.get("point") is None:
                        continue
                    acc.setdefault((norm_name(o.get("description")), stat), []).append(o["point"])
        for (name, stat), pts in acc.items():
            pts.sort()
            lines.setdefault(name, {})[stat] = pts[len(pts) // 2]  # ligne médiane
    save_json(path, lines, compact=False)
    print(f"Lignes : {len(lines)} joueurs")


def main():
    today = now_et().date()
    cur = season_of(today)
    hist = int(os.environ.get("HISTORY_SEASONS", "2"))
    seasons = list(range(cur - hist, cur + 1))
    print(f"Saisons suivies : {seasons}")
    teams = fetch_teams()
    sync_games(seasons, int(os.environ.get("MAX_NEW_GAMES", "6000")))
    sync_schedule()
    sync_injuries(teams)
    try:
        sync_odds()
    except Exception as e:
        print(f"Lignes : erreur {e}")


if __name__ == "__main__":
    main()
