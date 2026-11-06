"""MatchUp Perso — partie tennis (ATP + WTA).

Collecte (ESPN, gratuit) les résultats des dernières saisons et le programme du jour,
puis calcule pour chaque match : Elo global et par surface, probabilité de victoire,
face à face, forme, fatigue, styles de jeu (fichier data/tennis_styles.json) et,
si une clé The Odds API est fournie, les « value signals ».

Variables d'environnement :
  ODDS_API_KEY             clé The Odds API (facultatif, partagée avec la NBA)
  TENNIS_HISTORY_MONTHS    mois d'historique (défaut 34, soit depuis janvier 2024)
  TENNIS_ODDS_MIN_HOURS    délai mini entre deux relevés de cotes (défaut 20 h, préserve le quota)
"""
import os
import sys
import json
import math
import time
import datetime as dt
import urllib.parse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, SITE_DATA, load_json, save_json, norm_name

ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"
TDIR = os.path.join(RAW, "tennis")
TOURS = ("atp", "wta")
STYLE_FR = {"GS": "Gros serveur", "SC": "Serveur-cogneur", "AF": "Attaquant de fond de court",
            "FP": "Frappeur à plat", "CA": "Contre-attaquant", "TL": "Terrien lifteur",
            "JC": "Joueur complet", "CR": "Créatif / toucher"}
SURF_FR = {"hard": "dur", "clay": "terre battue", "grass": "gazon"}


def get_json(url):
    from fetch import get_json as gj  # même client HTTP que la NBA (reprises, délais)
    return gj(url)


# ====================================================================== surfaces
CLAY = ["roland garros", "french open", "monte", "madrid", "rome", "italian", "internazionali",
        "barcelona", "hamburg", "geneva", "lyon", "munich", "bmw open", "estoril", "marrakech",
        "hassan", "houston", "clay court", "bucharest", "buenos aires", "argentina open", "rio open",
        "santiago", "chile", "cordoba", "bastad", "nordea", "gstaad", "swiss open", "umag",
        "croatia open", "kitzbuhel", "generali", "charleston", "credit one", "bogota", "colsanitas",
        "rabat", "strasbourg", "parma", "palermo", "iasi", "budapest", "lausanne", "rouen", "oeiras",
        "cagliari", "portoroz", "bol open", "kitzbühel", "aix", "tiriac", "srpska", "banja luka"]
GRASS = ["wimbledon", "queen", "halle", "terra wortmann", "hertogenbosch", "libema", "rosmalen",
         "eastbourne", "mallorca", "nottingham", "birmingham", "berlin", "bad homburg", "newport",
         "hall of fame", "lexus", "boss open"]


def surface_of(name, date):
    n = (name or "").lower()
    month = int(date[5:7]) if date else 0
    if "stuttgart" in n:
        return "grass" if month in (6, 7) else "clay"
    if any(k in n for k in GRASS):
        return "grass"
    if any(k in n for k in CLAY):
        return "clay"
    return "hard"


# ====================================================================== collecte
def parse_events(data, tour):
    """Scoreboard ESPN -> liste de matchs de simple normalisés."""
    want = "women" if tour == "wta" else "men"
    out = []
    for e in data.get("events", []):
        tname = e.get("name") or e.get("shortName") or ""
        for g in e.get("groupings", []) or []:
            gr = g.get("grouping") or {}
            slug = (gr.get("slug") or gr.get("displayName") or "").lower()
            if "single" not in slug:
                continue
            if want == "men" and "women" in slug:
                continue
            for c in g.get("competitions", []) or []:
                comps = sorted(c.get("competitors", []) or [], key=lambda x: x.get("order", 0))
                if len(comps) != 2:
                    continue
                players = []
                for p in comps:
                    a = p.get("athlete") or {}
                    name = a.get("displayName") or a.get("fullName") or p.get("displayName")
                    if not name or name.upper().startswith("TBD"):
                        break
                    flag = a.get("flag") or {}
                    players.append({
                        "id": str(a.get("id") or p.get("id") or norm_name(name)),
                        "name": name,
                        "cc": (flag.get("alt") if isinstance(flag, dict) else None) or a.get("flagAltText") or "",
                        "win": bool(p.get("winner")),
                        "sets": [[s.get("value"), s.get("tiebreak")] for s in (p.get("linescores") or [])],
                    })
                if len(players) != 2:
                    continue
                st = (c.get("status") or {}).get("type") or {}
                date = (c.get("date") or c.get("startDate") or e.get("date") or "")[:16]
                desc = " ".join(str(st.get(k) or "") for k in ("name", "description", "detail")).lower()
                out.append({
                    "id": str(c.get("id")), "tour": tour, "date": date,
                    "event": tname, "eid": str(e.get("id")),
                    "round": (c.get("round") or {}).get("displayName") or "",
                    "state": st.get("state"), "done": bool(st.get("completed")),
                    "walkover": "walkover" in desc, "retired": "retire" in desc,
                    "detail": st.get("shortDetail") or st.get("detail") or "",
                    "surface": surface_of(tname, date),
                    "p": players,
                })
    return out


def month_iter(n_months):
    d = dt.date.today().replace(day=1)
    months = []
    for _ in range(n_months):
        months.append(d)
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return sorted(months)


def sync_history():
    n = int(os.environ.get("TENNIS_HISTORY_MONTHS", "34"))
    today = dt.date.today()
    fetched = 0
    for tour in TOURS:
        for m in month_iter(n):
            path = os.path.join(TDIR, tour, f"{m:%Y-%m}.json")
            end = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            fresh = (today - end).days > 10  # mois terminé depuis 10 j : figé
            if os.path.exists(path) and fresh:
                continue
            try:
                data = get_json(f"{ESPN}/{tour}/scoreboard?dates={m:%Y%m%d}-{end:%Y%m%d}&limit=1000")
                matches = [x for x in parse_events(data, tour) if x["done"] and not x["walkover"]]
            except Exception as ex:
                print(f"  ! {tour} {m:%Y-%m}: {ex}")
                matches = []
            if not matches and m.month != 12:
                # repli : jour par jour si la plage de dates n'est pas acceptée
                seen = {}
                day = m
                while day <= min(end, today):
                    try:
                        for x in parse_events(get_json(f"{ESPN}/{tour}/scoreboard?dates={day:%Y%m%d}"), tour):
                            if x["done"] and not x["walkover"]:
                                seen[x["id"]] = x
                    except Exception:
                        pass
                    day += dt.timedelta(days=1)
                    time.sleep(0.15)
                matches = list(seen.values())
            save_json(path, matches)
            fetched += 1
            time.sleep(0.3)
    print(f"Tennis : {fetched} mois (re)téléchargés")


def sync_today():
    out = []
    for tour in TOURS:
        seen = set()
        for q in ("", f"?dates={dt.date.today():%Y%m%d}"):
            try:
                data = get_json(f"{ESPN}/{tour}/scoreboard{q}")
            except Exception as ex:
                print(f"  ! programme {tour}: {ex}")
                continue
            for m in parse_events(data, tour):
                if m["id"] not in seen:
                    seen.add(m["id"])
                    out.append(m)
    rk = {}
    for tour in TOURS:
        try:
            data = get_json(f"{ESPN}/{tour}/rankings")
            for x in (data.get("rankings") or [{}])[0].get("ranks", []):
                a = x.get("athlete") or {}
                if a.get("displayName"):
                    rk[norm_name(a["displayName"])] = {"rank": x.get("current"), "pts": x.get("points")}
        except Exception as ex:
            print(f"  ! classement {tour}: {ex}")
    save_json(os.path.join(TDIR, "today.json"), {"matches": out, "ranks": rk})
    print(f"Tennis : {len(out)} matchs dans le programme, {len(rk)} classés")


def sync_odds():
    key = os.environ.get("ODDS_API_KEY", "").strip()
    path = os.path.join(TDIR, "odds.json")
    if not key:
        print("Tennis cotes : pas de clé, étape ignorée")
        return
    prev = load_json(path, {})
    min_h = float(os.environ.get("TENNIS_ODDS_MIN_HOURS", "20"))
    if prev.get("at"):
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(prev["at"])).total_seconds() / 3600
        if age < min_h:
            print(f"Tennis cotes : relevé de il y a {age:.0f} h conservé (quota préservé)")
            return
    base = "https://api.the-odds-api.com/v4/sports"
    sports = get_json(f"{base}?apiKey={key}")  # cet appel ne consomme pas de crédit
    keys = [s["key"] for s in sports if s.get("active") and s["key"].startswith(("tennis_atp", "tennis_wta"))]
    games = []
    for k in keys:
        q = urllib.parse.urlencode({"apiKey": key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"})
        try:
            for ev in get_json(f"{base}/{k}/odds?{q}"):
                best = {}
                for bk in ev.get("bookmakers", []):
                    for mk in bk.get("markets", []):
                        for o in mk.get("outcomes", []):
                            best[o["name"]] = max(best.get(o["name"], 0), o.get("price") or 0)
                games.append({"start": ev.get("commence_time"), "odds": best})
        except Exception as ex:
            print(f"  ! cotes {k}: {ex}")
    save_json(path, {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "games": games})
    print(f"Tennis cotes : {len(games)} matchs ({len(keys)} tournois)")


# ====================================================================== moteur
class Elo:
    def __init__(self):
        self.r = defaultdict(lambda: 1500.0)
        self.n = defaultdict(int)

    def p(self, a, b):
        return 1 / (1 + 10 ** ((self.r[b] - self.r[a]) / 400))

    def update(self, w, l):
        pw = self.p(w, l)
        kw = 250 / (self.n[w] + 5) ** 0.4
        kl = 250 / (self.n[l] + 5) ** 0.4
        self.r[w] += kw * (1 - pw)
        self.r[l] -= kl * (1 - pw)
        self.n[w] += 1
        self.n[l] += 1


def load_styles():
    data = load_json(os.path.join(RAW, "tennis_styles.json"), {"players": {}})
    by_norm, by_tokens, by_last = {}, {}, defaultdict(list)
    for k, v in data["players"].items():
        by_norm[k] = v
        toks = k.split()
        by_tokens[frozenset(toks)] = v
        by_last[(toks[-1], toks[0][0])].append(v)
    def find(name):
        k = norm_name(name)
        if k in by_norm:
            return by_norm[k]
        toks = k.split()
        v = by_tokens.get(frozenset(toks))
        if v:
            return v
        if toks:
            c = by_last.get((toks[-1], toks[0][0]), [])
            if len(c) == 1:
                return c[0]
        return None
    return find


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def inv_logit(x):
    return 1 / (1 + math.exp(-x))


def analyze():
    hist = []
    for tour in TOURS:
        d = os.path.join(TDIR, tour)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                hist += load_json(os.path.join(d, f), [])
    seen, matches = set(), []
    for m in hist:
        if m["id"] in seen or not any(p["win"] for p in m["p"]):
            continue
        seen.add(m["id"])
        matches.append(m)
    matches.sort(key=lambda m: m["date"])
    find_style = load_styles()
    tdata = load_json(os.path.join(TDIR, "today.json"), {"matches": [], "ranks": {}})
    odds = load_json(os.path.join(TDIR, "odds.json"), {}).get("games", [])

    elo = {t: Elo() for t in TOURS}
    selo = {(t, s): Elo() for t in TOURS for s in ("hard", "clay", "grass")}
    log = defaultdict(list)            # id joueur -> historique
    names = {}
    style_rec = defaultdict(lambda: [0, 0])   # (tour, styleA, styleB, surface|'all') -> [victoires A, total]

    def sty(name):
        s = find_style(name)
        return s["style"] if s else None

    for m in matches:
        a, b = m["p"]
        w, l = (a, b) if a["win"] else (b, a)
        t = m["tour"]
        pre_w = elo[t].p(w["id"], l["id"])
        elo[t].update(w["id"], l["id"])
        selo[(t, m["surface"])].update(w["id"], l["id"])
        nsets = max(len(a["sets"]), len(b["sets"]))
        score = " ".join(f"{int(x[0])}-{int(y[0])}" + (f"({int(min(x[1] or 99, y[1] or 99))})" if (x[1] or y[1]) else "")
                         for x, y in zip(w["sets"], l["sets"]) if x[0] is not None and y[0] is not None)
        for me, op, won in ((w, l, 1), (l, w, 0)):
            names[me["id"]] = me["name"]
            log[me["id"]].append({"d": m["date"][:10], "o": op["name"], "oid": op["id"], "w": won,
                                  "s": m["surface"], "ev": m["event"], "r": m["round"], "sc": score,
                                  "sets": nsets, "ret": 1 if m["retired"] else 0,
                                  "os": sty(op["name"]), "pe": round(pre_w if won else 1 - pre_w, 3)})
        sw, sl = sty(w["name"]), sty(l["name"])
        if sw and sl and sw != sl:
            for surf in (m["surface"], "all"):
                style_rec[(t, sw, sl, surf)][0] += 1
                style_rec[(t, sw, sl, surf)][1] += 1
                style_rec[(t, sl, sw, surf)][1] += 1

    now = dt.datetime.now(dt.timezone.utc)
    lo, hi = (now - dt.timedelta(hours=8)).isoformat()[:16], (now + dt.timedelta(hours=40)).isoformat()[:16]
    ranks = tdata.get("ranks", {})
    out = []
    for m in tdata["matches"]:
        if m["walkover"] or not (lo <= m["date"] <= hi):
            continue
        if m["state"] == "post" and m["date"] < (now - dt.timedelta(hours=8)).isoformat()[:16]:
            continue
        t, surf = m["tour"], m["surface"]
        a, b = m["p"]
        E, S = elo[t], selo[(t, surf)]
        p_all = E.p(a["id"], b["id"])
        p_surf = S.p(a["id"], b["id"])
        p_elo = 0.5 * p_all + 0.5 * p_surf
        side = []
        for me, op in ((a, b), (b, a)):
            L = log.get(me["id"], [])
            st = find_style(me["name"])
            ost = find_style(op["name"])
            last = L[-10:]
            yr = [x for x in L if x["d"] >= (now - dt.timedelta(days=365)).date().isoformat()]
            yr_s = [x for x in yr if x["s"] == surf]
            d7 = [x for x in L if x["d"] >= (now - dt.timedelta(days=7)).date().isoformat()]
            d3 = [x for x in L if x["d"] >= (now - dt.timedelta(days=3)).date().isoformat()]
            vs_style = [x for x in L if ost and x["os"] == ost["style"]]
            vs_style_s = [x for x in vs_style if x["s"] == surf]
            rk = ranks.get(norm_name(me["name"]), {})
            side.append({
                "id": me["id"], "name": me["name"], "cc": me.get("cc", ""), "rank": rk.get("rank"),
                "elo": round(E.r[me["id"]]), "selo": round(S.r[me["id"]]), "n": E.n[me["id"]], "ns": S.n[me["id"]],
                "style": st["style"] if st else None, "style_note": st["note"] if st else None,
                "style_src": st["source"] if st else None,
                "form": "".join("V" if x["w"] else "D" for x in last),
                "yr": [sum(x["w"] for x in yr), len(yr)], "yr_s": [sum(x["w"] for x in yr_s), len(yr_s)],
                "d7": len(d7), "d7_sets": sum(x["sets"] for x in d7), "d3": len(d3),
                "vs_style": [sum(x["w"] for x in vs_style), len(vs_style)],
                "vs_style_s": [sum(x["w"] for x in vs_style_s), len(vs_style_s)],
                "last": list(reversed(L[-12:])),
                "sets": me["sets"], "win": me["win"],
            })
        A, B = side
        h2h = [x for x in log.get(a["id"], []) if x["oid"] == b["id"]]
        h2h_s = [x for x in h2h if x["s"] == surf]

        # archétype : bilan du style A face au style B (surface du jour, sinon toutes surfaces)
        arche = None
        if A["style"] and B["style"] and A["style"] != B["style"]:
            ws, ns = style_rec.get((t, A["style"], B["style"], surf), [0, 0])
            wa, na = style_rec.get((t, A["style"], B["style"], "all"), [0, 0])
            arche = {"surf": [ws, ns], "all": [wa, na]}

        # modèle : Elo (global + surface) ajusté par l'archétype et la fatigue
        x = logit(p_elo)
        notes = []
        if arche:
            w_, n_ = arche["surf"] if arche["surf"][1] >= 30 else arche["all"]
            if n_ >= 30:
                adj = (w_ / n_ - 0.5) * (n_ / (n_ + 150)) * 1.2
                x += adj
                notes.append(round(adj, 3))
        fat = (A["d7_sets"] - B["d7_sets"]) * -0.02 + (A["d3"] - B["d3"]) * -0.03
        x += max(-0.15, min(0.15, fat))
        p_model = inv_logit(x)
        conf = min(A["n"], B["n"])

        # cotes et value
        oa = ob = None
        if odds:
            na_, nb_ = norm_name(a["name"]), norm_name(b["name"])
            la, lb = na_.split()[-1], nb_.split()[-1]
            for g in odds:
                keys = {norm_name(k): v for k, v in g["odds"].items()}
                ka = next((k for k in keys if k == na_ or k.split()[-1] == la), None)
                kb = next((k for k in keys if k == nb_ or k.split()[-1] == lb), None)
                if ka and kb and ka != kb:
                    oa, ob = keys[ka], keys[kb]
                    break
        value = None
        p_mkt = None
        if oa and ob:
            ia, ib = 1 / oa, 1 / ob
            p_mkt = ia / (ia + ib)  # probabilité du marché, marge retirée
        if oa and ob and conf >= 15:
            # prudence : la probabilité utilisée pour la value mélange modèle et marché à parts égales
            p_val = 0.5 * p_model + 0.5 * p_mkt
            for who, o, p in ((0, oa, p_val), (1, ob, 1 - p_val)):
                gap = p * o - 1
                if gap >= 0.08:
                    lvl = "Strong" if gap >= 0.25 else "Moderate" if gap >= 0.15 else "Slight"
                    if value is None or gap > value["gap"]:
                        value = {"side": who, "gap": round(gap, 3), "level": lvl, "odds": o,
                                 "fair": round(1 / p, 2), "p": round(p, 3)}

        # facteurs en clair
        fac = []
        fac.append([0, f"Elo {SURF_FR[surf]} : {A['name']} {A['selo']} contre {B['name']} {B['selo']} ; Elo global {A['elo']} contre {B['elo']}."])
        if h2h:
            wa = sum(x["w"] for x in h2h)
            wb = len(h2h) - wa
            ws_ = sum(x["w"] for x in h2h_s)
            on_s = f" ({ws_}-{len(h2h_s) - ws_} sur {SURF_FR[surf]})" if h2h_s else ""
            if wa == wb:
                fac.append([0, f"Face à face équilibré : {wa}-{wb}{on_s}."])
            else:
                lead = A["name"] if wa > wb else B["name"]
                fac.append([1 if wa > wb else -1, f"Face à face : {lead} mène {max(wa, wb)}-{min(wa, wb)}{on_s}."])
        if arche and (arche["surf"][1] >= 30 or arche["all"][1] >= 30):
            w_, n_ = arche["surf"] if arche["surf"][1] >= 30 else arche["all"]
            where = f"sur {SURF_FR[surf]}" if arche["surf"][1] >= 30 else "toutes surfaces"
            pct = round(100 * w_ / n_)
            fac.append([1 if pct >= 55 else -1 if pct <= 45 else 0,
                        f"Archétype : les « {STYLE_FR[A['style']]} » gagnent {pct} % de leurs matchs contre les « {STYLE_FR[B['style']]} » {where} ({n_} matchs)."])
        for P in (A, B):
            if P["d7"] >= 4 or P["d3"] >= 2:
                fac.append([-1 if P is A else 1, f"Fatigue : {P['name']} a joué {P['d7']} matchs ({P['d7_sets']} sets) ces 7 derniers jours."])
            if P["yr_s"][1] >= 8:
                pct = round(100 * P["yr_s"][0] / P["yr_s"][1])
                if pct >= 70 or pct <= 40:
                    fac.append([(1 if pct >= 70 else -1) * (1 if P is A else -1),
                                f"{P['name']} : {P['yr_s'][0]}-{P['yr_s'][1] - P['yr_s'][0]} sur {SURF_FR[surf]} sur 12 mois ({pct} %)."])
            f5 = P["form"][-5:]
            if len(f5) == 5 and f5.count("V") >= 4:
                fac.append([1 if P is A else -1, f"{P['name']} est en forme : {f5.count('V')} victoires sur ses 5 derniers matchs."])
        if conf < 15:
            fac.append([0, "Peu de matchs dans l'historique pour l'un des deux joueurs : probabilité moins fiable."])

        out.append({
            "id": m["id"], "tour": t, "date": m["date"], "event": m["event"], "round": m["round"],
            "surface": surf, "state": m["state"], "detail": m["detail"],
            "p_elo": round(p_elo, 3), "p_all": round(p_all, 3), "p_surf": round(p_surf, 3),
            "p": round(p_model, 3), "conf": conf, "odds": [oa, ob], "value": value,
            "p_mkt": round(p_mkt, 3) if p_mkt else None,
            "h2h": [{k: x[k] for k in ("d", "w", "s", "ev", "r", "sc")} for x in reversed(h2h)],
            "arche": arche, "fac": fac, "A": A, "B": B,
        })
    out.sort(key=lambda m: (m["state"] == "post", m["date"]))
    save_json(os.path.join(SITE_DATA, "tennis.json"), {
        "generated": now.isoformat(), "n_hist": len(matches), "has_odds": bool(odds),
        "styles": STYLE_FR, "matches": out,
    })
    print(f"Tennis : {len(out)} matchs analysés ({len(matches)} matchs d'historique)")


def main():
    os.makedirs(TDIR, exist_ok=True)
    for step in (sync_history, sync_today, sync_odds):
        try:
            step()
        except Exception as ex:
            print(f"Tennis : étape {step.__name__} en erreur : {ex}")
    analyze()


if __name__ == "__main__":
    if "--analyze-only" in sys.argv:
        analyze()
    else:
        main()
