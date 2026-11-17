"""Moteur de projection : prévoit la stat de chaque joueur pour le match du soir.

Principe
  projection = combinaison de paramètres connus AVANT le match :
    moyenne de saison (mêlée à la saison passée en début de saison), 10 et 5 derniers matchs,
    défense adverse sur son poste, rythme attendu, domicile, back-to-back,
    part de la production des coéquipiers absents, risque de blow-out (titulaires / banc),
    tendance du temps de jeu.
  Les poids sont appris par régression sur les matchs passés (une régression par stat),
  en ne regardant jamais l'avenir : chaque match est prédit avec les seules données d'avant.
  La dispersion (écart-type) est apprise aussi, ce qui donne une probabilité de passer la ligne.

Validation
  Le modèle est entraîné sur les 70 % de matchs les plus anciens et testé sur les 30 % restants.
  Les résultats du test (précision, taux de réussite par niveau de confiance) sont publiés sur le site.
"""
import math
from collections import defaultdict, deque

from common import STATS, stat_value, pos_bucket
from blowout import p_blowout

STAT_KEYS = list(STATS.keys())
FEATS = ["const", "moy", "l10", "l5", "def", "rythme", "dom", "b2b", "abs", "bo_tit", "bo_banc", "minutes",
         "moy_fiable", "saison_passee"]
PRIOR_GAMES = 5       # poids de la saison passée en début de saison
K_DEF_MIN = 1500      # minutes « virtuelles » pour stabiliser la défense par poste
K_PACE = 10           # matchs « virtuels » pour stabiliser le rythme
CORE_MPG, CORE_GP = 15, 5


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def ols(X, y, ridge=1e-3):
    n = len(X[0])
    A = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    for r, t in zip(X, y):
        for i in range(n):
            ri = r[i]
            if ri == 0:
                continue
            b[i] += ri * t
            Ai = A[i]
            for j in range(n):
                Ai[j] += ri * r[j]
    for i in range(n):
        A[i][i] += ridge * (A[i][i] or 1)
    for i in range(n):
        piv = max(range(i, n), key=lambda k: abs(A[k][i]))
        A[i], A[piv] = A[piv], A[i]
        b[i], b[piv] = b[piv], b[i]
        p = A[i][i] or 1e-12
        for j in range(i + 1, n):
            f = A[j][i] / p
            if f:
                A[j] = [a - f * c for a, c in zip(A[j], A[i])]
                b[j] -= f * b[i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (b[i] - sum(A[i][j] * x[j] for j in range(i + 1, n))) / (A[i][i] or 1e-12)
    return x


class State:
    """État glissant de la ligue : tout ce qu'on sait avant le prochain match."""

    def __init__(self):
        self.ps = defaultdict(lambda: defaultdict(float))       # (pid, saison) -> sommes
        self.pts_ = defaultdict(lambda: defaultdict(float))     # (pid, équipe, saison) -> sommes
        self.recent = defaultdict(lambda: deque(maxlen=10))     # pid -> 10 derniers matchs
        self.last_team = {}                                     # pid -> (équipe, date)
        self.last_for = {}                                      # (pid, équipe) -> date
        self.pos = {}
        self.dvp = defaultdict(lambda: defaultdict(float))      # (déf, saison, poste) -> sommes
        self.lg = defaultdict(lambda: defaultdict(float))       # (saison, poste) -> sommes
        self.pace = defaultdict(lambda: [0.0, 0])               # (équipe, saison)
        self.lg_pace = defaultdict(lambda: [0.0, 0])            # saison
        self.margin = defaultdict(lambda: [0.0, 0])             # (équipe, saison)
        self.team_tot = defaultdict(lambda: defaultdict(float)) # (équipe, saison) -> sommes stats + matchs
        self.team_dates = defaultdict(set)                      # équipe -> dates jouées

    # ---------------------------------------------------------------- lectures
    def player_avg(self, pid, season, s):
        cur = self.ps.get((pid, season))
        prev = self.ps.get((pid, season - 1))
        n = cur["n"] if cur else 0
        tot = cur[s] if cur else 0.0
        if prev and prev["n"] >= 5:
            pa = prev[s] / prev["n"]
            k = PRIOR_GAMES
        else:
            pa, k = 0.0, 0
        if n + k == 0:
            return None, 0
        return (tot + k * pa) / (n + k), n

    def mins(self, pid, season):
        cur = self.ps.get((pid, season))
        if cur and cur["n"]:
            return cur["min"] / cur["n"]
        prev = self.ps.get((pid, season - 1))
        return prev["min"] / prev["n"] if prev and prev["n"] else None

    def recent_avg(self, pid, s, k):
        r = list(self.recent.get(pid, []))[-k:]
        return sum(x[s] for x in r) / len(r) if r else None

    def recent_min(self, pid, k):
        r = list(self.recent.get(pid, []))[-k:]
        return sum(x["min"] for x in r) / len(r) if r else None

    def def_ratio(self, team, season, bucket, s):
        L = self.lg.get((season, bucket))
        if not L or L["min"] < 2000:
            L = self.lg.get((season - 1, bucket)) or L
        if not L or not L["min"]:
            return 1.0
        lg_rate = L[s] / L["min"]
        if not lg_rate:
            return 1.0
        prev = self.dvp.get((team, season - 1, bucket))
        prior = prev[s] / prev["min"] if prev and prev["min"] > 500 else lg_rate
        D = self.dvp.get((team, season, bucket), {})
        rate = (D.get(s, 0.0) + K_DEF_MIN * prior) / (D.get("min", 0.0) + K_DEF_MIN)
        return rate / lg_rate

    def team_pace(self, team, season):
        cur = self.pace.get((team, season), [0.0, 0])
        prev = self.pace.get((team, season - 1), [0.0, 0])
        lg = self.league_pace(season)
        prior = prev[0] / prev[1] if prev[1] >= 20 else lg
        return (cur[0] + K_PACE * prior) / (cur[1] + K_PACE)

    def league_pace(self, season):
        c = self.lg_pace.get(season, [0.0, 0])
        if c[1] >= 50:
            return c[0] / c[1]
        p = self.lg_pace.get(season - 1, [0.0, 0])
        return p[0] / p[1] if p[1] else 99.0

    def rating(self, team, season):
        cur = self.margin.get((team, season), [0.0, 0])
        prev = self.margin.get((team, season - 1), [0.0, 0])
        pr = (prev[0] / prev[1]) * 0.6 if prev[1] else 0.0
        return (cur[0] + 10 * pr) / (cur[1] + 10)

    def core(self, team, season):
        out = []
        for (pid, t, se), d in self.pts_.items():
            if t == team and se == season and d["n"] >= CORE_GP and d["min"] / d["n"] >= CORE_MPG:
                out.append((pid, d))
        return out

    def missing_share(self, team, season, date, present, me, s, absent_ids=None):
        """Part de la production de l'équipe (stat s) assurée par les titulaires absents."""
        tt = self.team_tot.get((team, season))
        if not tt or not tt["g"]:
            return 0.0
        team_pg = tt[s] / tt["g"]
        if team_pg <= 0:
            return 0.0
        miss = 0.0
        for pid, d in self.core(team, season):
            if pid == me:
                continue
            if absent_ids is not None:
                if pid not in absent_ids:
                    continue
            else:
                if pid in present:
                    continue
                lt = self.last_team.get(pid)
                if not lt or lt[0] != team:
                    continue  # transféré ailleurs
                last = self.last_for.get((pid, team))
                if not last or _days(last, date) > 20:
                    continue
            miss += d[s] / d["n"]
        return min(0.6, miss / team_pg)

    # ---------------------------------------------------------------- features
    def features(self, pid, season, team, opp, home, date, s, bucket, present=None,
                 absent_ids=None, b2b=False, pb=0.0):
        A, n = self.player_avg(pid, season, s)
        if A is None:
            return None
        l10 = self.recent_avg(pid, s, 10)
        l5 = self.recent_avg(pid, s, 5)
        if l10 is None:
            l10 = l5 = A
        m_s = self.mins(pid, season) or 0
        m5 = self.recent_min(pid, 5) or m_s
        mtr = max(-0.5, min(0.5, (m5 - m_s) / m_s)) if m_s else 0.0
        dr = self.def_ratio(opp, season, bucket, s)
        lgp = self.league_pace(season)
        pr = ((self.team_pace(team, season) + self.team_pace(opp, season)) / 2) / lgp if lgp else 1.0
        ms = self.missing_share(team, season, date, present or set(), pid, s, absent_ids)
        prev = self.ps.get((pid, season - 1))
        pa = prev[s] / prev["n"] if prev and prev["n"] >= 10 else A
        rel = min(n, 40) / 40  # plus il a joué de matchs cette saison, plus sa moyenne est fiable
        star = 1.0 if m_s >= 30 else 0.0
        bench = 1.0 if m_s < 22 else 0.0
        x = [1.0, A, l10, l5, A * (dr - 1), A * (pr - 1), A * (1 if home else -1) * 0.5,
             A * (1.0 if b2b else 0.0), A * ms, A * pb * star, A * pb * bench, A * mtr,
             A * rel, pa]
        meta = {"A": A, "n": n, "l10": l10, "l5": l5, "def": dr, "pace": pr, "miss": ms,
                "pb": pb, "mpg": m_s, "m5": m5}
        return x, meta

    # ---------------------------------------------------------------- mise à jour après un match
    def update(self, g, poss):
        s_ = g["season"]
        h, a = g["home"]["abbr"], g["away"]["abbr"]
        opp_of = {h: a, a: h}
        margin = (g["home"]["score"] or 0) - (g["away"]["score"] or 0)
        for t, m in ((h, margin), (a, -margin)):
            self.margin[(t, s_)][0] += m
            self.margin[(t, s_)][1] += 1
            self.team_dates[t].add(g["date"])
        for t in (h, a):
            pc = (poss[h] + poss[a]) / 2
            self.pace[(t, s_)][0] += pc
            self.pace[(t, s_)][1] += 1
        self.lg_pace[s_][0] += (poss[h] + poss[a]) / 2
        self.lg_pace[s_][1] += 1
        for t in (h, a):
            self.team_tot[(t, s_)]["g"] += 1
        for p in g["players"]:
            if p.get("dnp") or not p.get("min") or p["team"] not in opp_of:
                continue
            pid, t = p["id"], p["team"]
            b = pos_bucket(p.get("pos") or self.pos.get(pid, ""))
            if p.get("pos"):
                self.pos[pid] = p["pos"]
            vals = {k: stat_value(p, k) for k in STAT_KEYS}
            vals["min"] = p["min"]
            for D in (self.ps[(pid, s_)], self.pts_[(pid, t, s_)]):
                D["n"] += 1
                D["min"] += p["min"]
                for k in STAT_KEYS:
                    D[k] += vals[k]
            self.recent[pid].append(vals)
            self.last_team[pid] = (t, g["date"])
            self.last_for[(pid, t)] = g["date"]
            for k in STAT_KEYS:
                self.team_tot[(t, s_)][k] += vals[k]
            Dv = self.dvp[(opp_of[t], s_, b)]
            Lg = self.lg[(s_, b)]
            Dv["min"] += p["min"]
            Lg["min"] += p["min"]
            for k in STAT_KEYS:
                Dv[k] += vals[k]
                Lg[k] += vals[k]


def _days(d1, d2):
    import datetime as dt
    return (dt.date.fromisoformat(d2) - dt.date.fromisoformat(d1)).days


def game_poss(g):
    agg = defaultdict(lambda: defaultdict(float))
    for p in g["players"]:
        if p.get("dnp"):
            continue
        for k in ("fga", "fta", "oreb", "tov"):
            agg[p["team"]][k] += p.get(k, 0) or 0
    out = {}
    for t in (g["home"]["abbr"], g["away"]["abbr"]):
        A = agg[t]
        out[t] = A["fga"] + 0.44 * A["fta"] - A["oreb"] + A["tov"]
    return out


class Projector:
    def __init__(self, games, hca=1.8, slope=1.07, sigma_m=14.3):
        self.games = games
        self.hca, self.slope, self.sigma_m = hca, slope, sigma_m
        self.rows = {s: [] for s in STAT_KEYS}   # (date, x, y, meta)
        self._walk()
        self._fit()

    def _pb(self, st, h, a, season):
        m = self.hca + self.slope * (st.rating(h, season) - st.rating(a, season))
        return p_blowout(m, self.sigma_m)

    def _walk(self):
        st = State()
        for g in self.games:
            se = g["season"]
            h, a = g["home"]["abbr"], g["away"]["abbr"]
            pres = defaultdict(set)
            for p in g["players"]:
                if not p.get("dnp") and p.get("min"):
                    pres[p["team"]].add(p["id"])
            pb = self._pb(st, h, a, se)
            for p in g["players"]:
                if p.get("dnp") or not p.get("min") or p["team"] not in (h, a):
                    continue
                t = p["team"]
                o = a if t == h else h
                b2b = any(_days(d, g["date"]) == 1 for d in st.team_dates.get(t, ()) if d < g["date"])
                cur = st.ps.get((p["id"], se))
                n_tot = (cur["n"] if cur else 0)
                prev = st.ps.get((p["id"], se - 1))
                if n_tot < 5 and not (prev and prev["n"] >= 10):
                    continue
                bucket = pos_bucket(p.get("pos") or st.pos.get(p["id"], ""))
                for s in STAT_KEYS:
                    f = st.features(p["id"], se, t, o, t == h, g["date"], s, bucket,
                                    present=pres[t], b2b=b2b, pb=pb)
                    if f:
                        f[1]["pid"], f[1]["gid"] = p["id"], g["id"]
                        self.rows[s].append((g["date"], f[0], stat_value(p, s), f[1]))
            st.update(g, game_poss(g))
        self.state = st

    def _fit(self):
        self.coef, self.sig, self.report = {}, {}, {}
        dates = sorted({r[0] for r in self.rows["pts"]})
        self.cut = dates[int(len(dates) * 0.7)] if dates else "9999"
        for s in STAT_KEYS:
            R = self.rows[s]
            tr = [r for r in R if r[0] < self.cut]
            te = [r for r in R if r[0] >= self.cut]
            c = ols([r[1] for r in tr], [r[2] for r in tr])
            pred = lambda x: max(0.0, sum(ci * xi for ci, xi in zip(c, x)))
            # dispersion : écart absolu moyen en fonction de la projection
            bins = defaultdict(list)
            for r in tr:
                p = pred(r[1])
                bins[min(20, int(p / max(0.5, _unit(s))))].append(abs(r[2] - p))
            xs, ys, ws = [], [], []
            for k, v in bins.items():
                if len(v) >= 30:
                    xs.append((k + 0.5) * max(0.5, _unit(s)))
                    ys.append(sum(v) / len(v))
                    ws.append(len(v))
            if len(xs) >= 2:
                mx = sum(x * w for x, w in zip(xs, ws)) / sum(ws)
                my = sum(y * w for y, w in zip(ys, ws)) / sum(ws)
                vx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws)) or 1
                b1 = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws)) / vx
                b0 = my - b1 * mx
            else:
                b0, b1 = 1.0, 0.3
            sig = (max(0.3, b0), max(0.0, b1))
            self.coef[s], self.sig[s] = c, sig
            # rapport de test (matchs jamais vus)
            mae_m = mae_b = 0.0
            for r in te:
                mae_m += abs(r[2] - pred(r[1]))
                mae_b += abs(r[2] - r[3]["A"])
            n = len(te) or 1
            self.report[s] = {"n_train": len(tr), "n_test": len(te), "mae": round(mae_m / n, 2),
                              "mae_base": round(mae_b / n, 2)}
        # final : réentraîné sur tout l'historique pour les prévisions du soir
        self.test_rows = {s: [r for r in self.rows[s] if r[0] >= self.cut] for s in STAT_KEYS}
        self.coef_test = dict(self.coef)
        self.sig_test = dict(self.sig)
        for s in STAT_KEYS:
            R = self.rows[s]
            self.coef[s] = ols([r[1] for r in R], [r[2] for r in R])
        self.ctx_test = {s: self._ctx_mean(s, self.coef_test[s], [r for r in self.rows[s] if r[0] < self.cut])
                         for s in STAT_KEYS}
        self.ctx = {s: self._ctx_mean(s, self.coef[s], self.rows[s]) for s in STAT_KEYS}

    def _ctx_mean(self, s, coef, rows):
        tot = 0.0
        for r in rows:
            tot += sum(coef[i] * r[1][i] for i in CTX) / max(1e-6, r[3]["A"])
        return tot / max(1, len(rows))

    def context(self, s, x, meta, test=False):
        """Projection complète, projection « niveau habituel » (contexte neutre) et décalage
        du contexte du soir, en écarts-types. C'est ce décalage qui classe les conseils."""
        coefs = self.coef_test if test else self.coef
        coef = coefs[s]
        rel = self.ctx_test[s] if test else self.ctx[s]
        full, sd = self.project(s, x, coefs, self.sig_test if test else self.sig)
        ctx = sum(coef[i] * x[i] for i in CTX)
        usual = max(0.0, full - ctx + rel * meta["A"])
        return full, usual, (full - usual) / max(0.3, sd), sd

    # ---------------------------------------------------------------- prévision
    def project(self, s, x, coef=None, sig=None):
        c = (coef or self.coef)[s]
        p = max(0.0, sum(ci * xi for ci, xi in zip(c, x)))
        b0, b1 = (sig or self.sig)[s]
        sd = 1.2533 * (b0 + b1 * p)
        return p, sd

    def contributions(self, s, x, meta):
        """Décomposition lisible de la projection, en unités de la stat."""
        c = self.coef[s]
        A = meta["A"]
        base = c[0] + (c[1] + c[2] + c[3]) * A
        form = c[2] * (x[2] - A) + c[3] * (x[3] - A)
        parts = {"Base (saison)": base, "Forme récente": form}
        base = c[0] + (c[1] + c[2] + c[3]) * A + c[12] * x[12] + c[13] * x[13]
        parts = {"Base (saison)": base, "Forme récente": form}
        names = {4: "Défense adverse", 5: "Rythme", 6: "Domicile/extérieur", 7: "Back-to-back",
                 8: "Absences coéquipiers", 9: "Blow-out", 10: "Blow-out", 11: "Temps de jeu"}
        for i, nm in names.items():
            parts[nm] = parts.get(nm, 0.0) + c[i] * x[i]
        return parts


def p_over(line, proj, sd):
    return 1 - ncdf((line - proj) / max(0.3, sd))


def _unit(s):
    return {"pts": 2, "reb": 1, "ast": 1, "tpm": 0.5, "pr": 2, "pa": 2, "ra": 1, "pra": 3,
            "stl": 0.5, "blk": 0.5}[s]


PICK_STATS = ["pts", "reb", "ast", "tpm", "pr", "pa", "ra", "pra"]
MIN_LINE = {"pts": 4.5, "reb": 2.5, "ast": 2.5, "tpm": 2.5, "pr": 6.5, "pa": 6.5, "ra": 4.5, "pra": 9.5}
MIN_MPG_PICK, MIN_GP_PICK = 20, 8


CTX = [4, 5, 6, 7, 8, 9, 10, 11]   # indices des paramètres de contexte (défense … temps de jeu)


def market_line(meta, s=None):
    """Ligne approximative (moyenne pondérée récente, ajustée de la défense)."""
    base = 0.55 * meta["A"] + 0.30 * meta["l10"] + 0.15 * meta["l5"]
    base *= 1 + 0.5 * (meta["def"] - 1)
    return math.floor(base) + 0.5


def confidence(pc, n):
    """Probabilité ramenée vers 50 % quand l'échantillon du joueur est petit."""
    return 0.5 + (pc - 0.5) * min(1.0, n / 20)


def eligible(s, line, meta):
    return s in PICK_STATS and line >= MIN_LINE[s] and meta["n"] >= MIN_GP_PICK and meta["mpg"] >= MIN_MPG_PICK


def select(cands, k=10, per_game=3):
    """cands : dicts avec conf, pid, gid. Un conseil par joueur, 3 par match au plus."""
    out, seen_p, per_g = [], set(), defaultdict(int)
    for c in sorted(cands, key=lambda z: -z["conf"]):
        if c["pid"] in seen_p or per_g[c["gid"]] >= per_game:
            continue
        out.append(c)
        seen_p.add(c["pid"])
        per_g[c["gid"]] += 1
        if len(out) >= k:
            break
    return out


def backtest(P):
    """Test sur les matchs jamais vus, avec les règles des conseils du site.
    Ligne de référence = niveau habituel du joueur (contexte neutre), arrondie à x,5.
    Un conseil suit le sens du contexte du soir ; on mesure s'il passe."""
    labels = ["< 0,1", "0,1-0,2", "0,2-0,3", "0,3-0,4", "≥ 0,4"]
    bins = defaultdict(lambda: [0, 0])
    by_day = defaultdict(list)
    by_stat = defaultdict(lambda: [0, 0])
    for s in PICK_STATS:
        for d, x, y, meta in P.test_rows[s]:
            full, usual, shift, sd = P.context(s, x, meta, test=True)
            line = math.floor(usual) + 0.5
            if not eligible(s, line, meta):
                continue
            side = "over" if full > line else "under"
            won = (y > line) if side == "over" else (y < line)
            k = min(4, int(abs(shift) / 0.1))
            bins[k][0] += won
            bins[k][1] += 1
            by_day[d].append({"conf": abs(shift), "won": won, "pid": meta["pid"], "gid": meta["gid"], "s": s, "side": side})
    top = {"hit": 0, "n": 0, "days": 0, "top3": [0, 0], "over": 0}
    for d, lst in by_day.items():
        sel = select(lst)
        top["hit"] += sum(c["won"] for c in sel)
        top["n"] += len(sel)
        top["days"] += 1
        top["top3"][0] += sum(c["won"] for c in sel[:3])
        top["top3"][1] += len(sel[:3])
        top["over"] += sum(c["side"] == "over" for c in sel)
        for c in sel:
            by_stat[c["s"]][0] += c["won"]
            by_stat[c["s"]][1] += 1
    return {"cut": P.cut, "by_shift": {labels[k]: {"hit": v[0], "n": v[1]} for k, v in sorted(bins.items())},
            "top": top, "by_stat": {s: {"hit": v[0], "n": v[1]} for s, v in by_stat.items()},
            "mae": {s: [P.report[s]["mae"], P.report[s]["mae_base"]] for s in PICK_STATS}}
