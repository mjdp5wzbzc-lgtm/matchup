"""Risque de blow-out (match plié, écart final de 20 points ou plus).

Modèle calibré sur l'historique :
  écart projeté = (note équipe dom. − note équipe ext.) + avantage du terrain − poids des absences
  note d'équipe = écart moyen de la saison, mélangé à la saison passée en début de saison
  poids d'un absent = sa production moyenne (Game Score), au-delà d'un remplaçant
La pente, l'avantage du terrain, le poids des absences et la dispersion sont ajustés
par régression sur les matchs passés, puis convertis en probabilité d'écart ≥ 20 pts.
"""
import math
from collections import defaultdict

BLOWOUT = 20      # écart final qui définit un blow-out
PRIOR_K = 10      # matchs « virtuels » de la saison passée en début de saison
MIN_MPG = 15      # joueur compté dans les absences au-delà de 15 min/match
MIN_GP = 8


def gmsc(p):
    return (p.get("pts", 0) + 0.4 * p.get("fgm", 0) - 0.7 * p.get("fga", 0)
            - 0.4 * (p.get("fta", 0) - p.get("ftm", 0)) + 0.7 * p.get("oreb", 0)
            + 0.3 * (p.get("reb", 0) - p.get("oreb", 0)) + p.get("stl", 0) + 0.7 * p.get("ast", 0)
            + 0.7 * p.get("blk", 0) - p.get("tov", 0))


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_blowout(margin, sigma):
    """Probabilité que l'écart final dépasse 20 points, d'un côté ou de l'autre."""
    return (1 - ncdf((BLOWOUT - margin) / sigma)) + ncdf((-BLOWOUT - margin) / sigma)


def _ols(X, y):
    """Moindres carrés (petit système, sans numpy)."""
    n = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(n)] for i in range(n)]
    b = [sum(r[i] * t for r, t in zip(X, y)) for i in range(n)]
    for i in range(n):  # élimination de Gauss
        piv = A[i][i] or 1e-9
        for j in range(i + 1, n):
            f = A[j][i] / piv
            A[j] = [a - f * c for a, c in zip(A[j], A[i])]
            b[j] -= f * b[i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (b[i] - sum(A[i][j] * x[j] for j in range(i + 1, n))) / (A[i][i] or 1e-9)
    return x


class BlowoutModel:
    def __init__(self, games):
        self.games = games
        self._player_values()
        self._rate_and_fit()

    # -- valeur des joueurs (par équipe et par saison) ---------------------------
    def _player_values(self):
        acc = defaultdict(lambda: {"g": 0, "min": 0.0, "gs": 0.0, "lo": "9999", "hi": "0000"})
        for g in self.games:
            for p in g["players"]:
                if p.get("dnp") or not p.get("min"):
                    continue
                a = acc[(p["id"], p["team"], g["season"])]
                a["g"] += 1
                a["min"] += p["min"]
                a["gs"] += gmsc(p)
                a["lo"] = min(a["lo"], g["date"])
                a["hi"] = max(a["hi"], g["date"])
        tot_min = sum(a["min"] for a in acc.values()) or 1
        lg_gs_min = sum(a["gs"] for a in acc.values()) / tot_min
        self.val = {}           # (pid, team, season) -> valeur au-dessus d'un remplaçant
        self.core = defaultdict(list)  # (team, season) -> joueurs importants
        for (pid, team, season), a in acc.items():
            mpg = a["min"] / a["g"]
            v = max(0.0, a["gs"] / a["g"] - 0.75 * lg_gs_min * mpg)  # remplaçant ≈ 75 % du rendement moyen
            self.val[(pid, team, season)] = v
            if a["g"] >= MIN_GP and mpg >= MIN_MPG:
                self.core[(team, season)].append((pid, a["lo"], a["hi"], v))

    def missing_value(self, team, season, date, present):
        return sum(v for pid, lo, hi, v in self.core.get((team, season), [])
                   if lo <= date <= hi and pid not in present)

    # -- notes d'équipe glissantes + calibration --------------------------------
    def _rate_and_fit(self):
        sums = defaultdict(lambda: [0.0, 0])   # (team, season) -> [somme des écarts, matchs]
        final = {}
        rows = []
        last_season = None
        for g in self.games:
            s = g["season"]
            if s != last_season and last_season is not None:
                for (t, ss), (tot, n) in list(sums.items()):
                    if ss == last_season and n:
                        final[(t, ss)] = tot / n
            last_season = s
            h, a = g["home"]["abbr"], g["away"]["abbr"]
            rh, ra = self.rating(h, s, sums, final), self.rating(a, s, sums, final)
            margin = (g["home"]["score"] or 0) - (g["away"]["score"] or 0)
            pres = {t: {p["id"] for p in g["players"] if p["team"] == t and not p.get("dnp") and p.get("min")}
                    for t in (h, a)}
            mh = self.missing_value(h, s, g["date"], pres[h])
            ma = self.missing_value(a, s, g["date"], pres[a])
            if sums[(h, s)][1] >= 3 and sums[(a, s)][1] >= 3 and margin:
                rows.append((rh - ra, mh - ma, margin))
            for t, m in ((h, margin), (a, -margin)):
                sums[(t, s)][0] += m
                sums[(t, s)][1] += 1
        for (t, ss), (tot, n) in sums.items():
            if ss == last_season and n:
                final[(t, ss)] = tot / n
        self.sums, self.final = sums, final
        if len(rows) >= 200:
            X = [[1.0, r[0], r[1]] for r in rows]
            y = [r[2] for r in rows]
            self.hca, self.slope, self.miss = _ols(X, y)
            res = [t - (self.hca + self.slope * x[1] + self.miss * x[2]) for x, t in zip(X, y)]
            self.sigma = math.sqrt(sum(e * e for e in res) / len(res))
        else:  # valeurs typiques NBA si pas assez d'historique
            self.hca, self.slope, self.miss, self.sigma = 2.5, 0.75, -0.6, 13.5
        self.miss = min(0.0, self.miss)  # un absent ne peut pas aider son équipe
        self.n_fit = len(rows)
        self.base_rate = (sum(1 for r in rows if abs(r[2]) >= BLOWOUT) / len(rows)) if rows else 0.15
        # contrôle : taux réel de blow-out selon la probabilité prédite
        buckets = defaultdict(lambda: [0, 0])
        for d, m, t in rows:
            p = p_blowout(self.hca + self.slope * d + self.miss * m, self.sigma)
            k = min(4, int(p / 0.1))
            buckets[k][0] += abs(t) >= BLOWOUT
            buckets[k][1] += 1
        self.calib = {k: (v[0], v[1]) for k, v in sorted(buckets.items())}

    def rating(self, team, season, sums=None, final=None):
        sums = self.sums if sums is None else sums
        final = self.final if final is None else final
        tot, n = sums.get((team, season), (0.0, 0))
        prev = final.get((team, season - 1), 0.0) * 0.6   # la saison passée compte à moitié environ
        return (tot + PRIOR_K * prev) / (n + PRIOR_K)

    def predict(self, home, away, season, miss_home, miss_away):
        rh, ra = self.rating(home, season), self.rating(away, season)
        margin = self.hca + self.slope * (rh - ra) + self.miss * (miss_home - miss_away)
        base = self.hca + self.slope * (rh - ra)
        return {
            "margin": round(margin, 1), "margin_full": round(base, 1),
            "p": round(p_blowout(margin, self.sigma), 3),
            "p_full": round(p_blowout(base, self.sigma), 3),
            "r_home": round(rh, 1), "r_away": round(ra, 1),
            "miss_home": round(-self.miss * miss_home, 1), "miss_away": round(-self.miss * miss_away, 1),
        }

    def level(self, p):
        if p >= max(0.40, 1.85 * self.base_rate):
            return 2
        if p >= max(0.30, 1.4 * self.base_rate):
            return 1
        return 0
