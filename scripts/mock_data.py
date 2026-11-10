"""Génère des données FICTIVES au même format que fetch.py, pour tester le site
sans connexion. Usage : python scripts/mock_data.py  (écrase data/)"""
import os
import sys
import random
import shutil
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, GAMES_DIR, LINES_DIR, now_et, save_json, norm_name

TEAMS = [("ATL", "Hawks"), ("BOS", "Celtics"), ("BKN", "Nets"), ("CHA", "Hornets"), ("CHI", "Bulls"),
         ("CLE", "Cavaliers"), ("DAL", "Mavericks"), ("DEN", "Nuggets"), ("DET", "Pistons"),
         ("GS", "Warriors"), ("HOU", "Rockets"), ("IND", "Pacers"), ("LAC", "Clippers"),
         ("LAL", "Lakers"), ("MEM", "Grizzlies"), ("MIA", "Heat"), ("MIL", "Bucks"),
         ("MIN", "Timberwolves"), ("NO", "Pelicans"), ("NY", "Knicks"), ("OKC", "Thunder"),
         ("ORL", "Magic"), ("PHI", "76ers"), ("PHX", "Suns"), ("POR", "Trail Blazers"),
         ("SAC", "Kings"), ("SA", "Spurs"), ("TOR", "Raptors"), ("UTAH", "Jazz"), ("WSH", "Wizards")]
FIRST = ["Jalen", "Marcus", "Tyrese", "Devin", "Jaylen", "Anthony", "Luka", "Victor", "Nikola", "Kevin",
         "Trae", "Scottie", "Paolo", "Franz", "Evan", "Cade", "Zion", "Darius", "Mikal", "Alperen",
         "Chet", "Shai", "Domantas", "Bam", "Jaren", "De'Aaron", "Donovan", "Damian", "Karl", "Rudy"]
LAST = ["Moreau", "Carter", "Bennett", "Lopez", "Okafor", "Diallo", "Fournier", "Petrov", "Hayes",
        "Brooks", "Mitchell", "Coleman", "Reed", "Barnes", "Ward", "Price", "Fisher", "Hughes",
        "Bryant", "Russell", "Griffin", "Sanders", "Perry", "Long", "Foster", "Simmons", "Wood",
        "Powell", "Jenkins", "Ross"]
POSITIONS = ["PG", "SG", "SF", "PF", "C", "PG", "SG", "SF", "PF", "C", "G", "F", "C"]


def main():
    random.seed(7)
    for d in (GAMES_DIR, LINES_DIR):
        shutil.rmtree(d, ignore_errors=True)
    teams = {a: {"id": str(i + 1), "abbr": a, "name": f"Ville {n}", "short": n, "color": None, "logo": None}
             for i, (a, n) in enumerate(TEAMS)}
    save_json(os.path.join(RAW, "teams.json"), teams, compact=False)

    # effectifs et profils
    pid = 1000
    roster, prof = {}, {}
    tdef = {a: {"inside": random.uniform(0.85, 1.15), "three": random.uniform(0.85, 1.15),
                "guard": random.uniform(0.85, 1.15), "pace": random.uniform(96, 104)} for a, _ in TEAMS}
    for a, _ in TEAMS:
        roster[a] = []
        for k, pos in enumerate(POSITIONS):
            pid += 1
            star = 1.0 if k < 5 else 0.55
            prof[str(pid)] = {
                "name": f"{random.choice(FIRST)} {random.choice(LAST)}", "pos": pos, "team": a,
                "min": (34 if k < 5 else 20 if k < 9 else 12) + random.uniform(-3, 3),
                "pts": (random.uniform(14, 29) if k < 5 else random.uniform(5, 12)),
                "reb": random.uniform(8, 12) * star if pos in ("C", "PF") else random.uniform(3, 6) * star,
                "ast": random.uniform(5, 9) * star if pos in ("PG", "G") else random.uniform(1.5, 4) * star,
                "three": random.uniform(0.2, 0.55) if pos != "C" else random.choice([0.05, 0.4]),
            }
            roster[a].append(str(pid))

    def box(team, opp, home):
        out = []
        for p in roster[team]:
            P = prof[p]
            if random.random() < 0.06:
                out.append({"id": p, "name": P["name"], "pos": P["pos"], "team": team, "starter": 0, "dnp": 1, "min": 0})
                continue
            b = "C" if P["pos"].startswith("C") else "G" if P["pos"] in ("PG", "SG", "G") else "F"
            dmod = {"C": tdef[opp]["inside"], "G": tdef[opp]["guard"], "F": 1.0}[b]
            pace = (tdef[team]["pace"] + tdef[opp]["pace"]) / 200
            mins = max(4, random.gauss(P["min"], 3.5))
            f = mins / P["min"] * pace * (1.03 if home else 0.97)
            pts = max(0, round(random.gauss(P["pts"] * f * dmod, P["pts"] * 0.28)))
            fga = max(1, round(pts / 2.2 + random.uniform(-2, 2)))
            tpa = round(fga * P["three"] * tdef[opp]["three"])
            tpm = min(tpa, max(0, round(tpa * random.uniform(0.25, 0.45))))
            fta = max(0, round(pts * 0.22 + random.uniform(-1, 1)))
            reb = max(0, round(random.gauss(P["reb"] * f, 2.2)))
            out.append({"id": p, "name": P["name"], "pos": P["pos"], "team": team,
                        "starter": 1 if roster[team].index(p) < 5 else 0, "min": round(mins, 1),
                        "pts": pts, "fga": fga, "fgm": min(fga, round(fga * random.uniform(0.38, 0.56))),
                        "tpa": tpa, "tpm": tpm, "fta": fta, "ftm": round(fta * 0.78),
                        "reb": reb, "oreb": round(reb * 0.25),
                        "ast": max(0, round(random.gauss(P["ast"] * f, 1.6))),
                        "stl": max(0, round(random.gauss(1.0 * f, 0.8))),
                        "blk": max(0, round(random.gauss((1.4 if b == "C" else 0.4) * f, 0.7))),
                        "tov": max(0, round(random.gauss(2 * f, 1)))})
        return out

    today = now_et().date()
    abbrs = [a for a, _ in TEAMS]
    gid = 500000
    for season, start, end in ((2026, dt.date(2025, 10, 21), dt.date(2026, 4, 12)),
                               (2027, dt.date(2026, 10, 20), today - dt.timedelta(days=1))):
        day = start
        while day <= end:
            random.shuffle(abbrs)
            n = random.randint(4, 7)
            for k in range(n):
                h, a = abbrs[2 * k], abbrs[2 * k + 1]
                gid += 1
                players = box(h, a, 1) + box(a, h, 0)
                sh = sum(p.get("pts", 0) for p in players if p["team"] == h)
                sa = sum(p.get("pts", 0) for p in players if p["team"] == a)
                save_json(os.path.join(GAMES_DIR, str(season), f"{gid}.json"), {
                    "id": str(gid), "date": day.isoformat(), "season": season, "stype": 2,
                    "home": {"abbr": h, "id": teams[h]["id"], "score": sh},
                    "away": {"abbr": a, "id": teams[a]["id"], "score": sa}, "players": players})
            day += dt.timedelta(days=1)

    random.shuffle(abbrs)
    games = []
    for k in range(9):
        h, a = abbrs[2 * k], abbrs[2 * k + 1]
        start = dt.datetime.combine(today, dt.time(19 + k % 3, 30 if k % 2 else 0)).replace(
            tzinfo=dt.timezone(dt.timedelta(hours=-5))).astimezone(dt.timezone.utc)
        games.append({"id": str(900000 + k), "start": start.isoformat().replace("+00:00", "Z"),
                      "home": h, "away": a, "state": "pre", "detail": "", "score": {}})
    save_json(os.path.join(RAW, "schedule.json"), {"days": [{"date": today.isoformat(), "games": games}]}, compact=False)

    inj = {}
    for g in games:
        for t in (g["home"], g["away"]):
            inj[t] = []
            for p in random.sample(roster[t], random.choice([0, 1, 2])):
                inj[t].append({"id": p, "name": prof[p]["name"], "pos": prof[p]["pos"],
                               "status": random.choice(["Out", "Out", "Day-To-Day", "Questionable"]),
                               "type": "Cheville", "comment": "Entorse de la cheville, réévalué demain."})
    inj["_updated"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_json(os.path.join(RAW, "injuries.json"), inj, compact=False)

    lines = {}
    for g in games[:5]:
        for t in (g["home"], g["away"]):
            for p in roster[t][:5]:
                lines[norm_name(prof[p]["name"])] = {"pts": round(prof[p]["pts"]) + 0.5}
    save_json(os.path.join(LINES_DIR, f"{today.isoformat()}.json"), lines, compact=False)
    print("Données fictives générées.")


if __name__ == "__main__":
    main()

