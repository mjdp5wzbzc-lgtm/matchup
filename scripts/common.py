"""Outils partagés : chemins, saisons, fuseau horaire, lecture/écriture JSON."""
import json
import os
import datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data")                  # cache brut (commité dans le dépôt)
GAMES_DIR = os.path.join(RAW, "games")            # un fichier par match normalisé
LINES_DIR = os.path.join(RAW, "lines")            # archive des lignes bookmakers
SITE_DATA = os.path.join(ROOT, "site", "data")    # données publiées pour le site

ET = ZoneInfo("America/New_York")

# Les 10 stats suivies : clé -> (libellé, composantes)
STATS = {
    "pts": ("Points", ["pts"]),
    "reb": ("Rebonds", ["reb"]),
    "ast": ("Passes", ["ast"]),
    "tpm": ("3 points", ["tpm"]),
    "pr":  ("Pts+Reb", ["pts", "reb"]),
    "pa":  ("Pts+Pas", ["pts", "ast"]),
    "ra":  ("Reb+Pas", ["reb", "ast"]),
    "pra": ("Pts+Reb+Pas", ["pts", "reb", "ast"]),
    "stl": ("Interceptions", ["stl"]),
    "blk": ("Contres", ["blk"]),
}

# Ordre des colonnes dans les journaux de match envoyés au site
LOG_FIELDS = ["date", "season", "opp", "home", "min", "pts", "reb", "ast", "tpm",
              "stl", "blk", "tov", "fgm", "fga", "tpa", "ftm", "fta", "oreb",
              "team", "starter", "event"]


def stat_value(p, key):
    return sum(p.get(c, 0) or 0 for c in STATS[key][1])


def now_et():
    return dt.datetime.now(ET)


def season_of(date):
    """Saison au format ESPN (année de fin) : oct. 2026 -> 2027."""
    return date.year + 1 if date.month >= 8 else date.year


def season_label(season):
    return f"{season - 1}-{str(season)[2:]}"


def season_bounds(season):
    """Fenêtre large d'une saison (présaison exclue plus tard via le type)."""
    return dt.date(season - 1, 10, 1), dt.date(season, 6, 30)


def pos_bucket(pos):
    """Ramène la position ESPN à Meneur/arrière (G), Ailier (F) ou Pivot (C)."""
    pos = (pos or "").upper()
    if not pos:
        return "F"
    if pos.startswith("C"):
        return "C"
    if pos in ("PF-C", "F-C"):
        return "C"
    if pos.startswith(("PG", "SG", "G")):
        return "G"
    return "F"


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, compact=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def norm_name(name):
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    for suf in (" jr", " sr", " iii", " ii", " iv"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return " ".join(s.split())
