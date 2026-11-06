# MatchUp Perso — ton analyseur NBA gratuit

Chaque soir, une fiche par joueur NBA sur 10 stats (points, rebonds, passes, 3 pts,
Pts+Reb, Pts+Pas, Reb+Pas, Pts+Reb+Pas, interceptions, contres) :

| Onglet | Ce qu'il montre |
|---|---|
| ⭐ Facteurs clés | Le résumé « en clair » : ce qui joue pour ou contre lui ce soir |
| 📈 Forme | 5 / 10 derniers matchs, graphique vs la ligne, détail match par match |
| 🆚 H2H | Tous ses matchs contre l'adversaire (3 saisons), taux de réussite vs la ligne |
| 🚑 Absences | Ses chiffres avec / sans chaque coéquipier absent ce soir |
| 🎯 Style de jeu | Son style (Pivot stretch, Meneur P&R, Sniper…) vs le profil de la défense adverse |
| 🛡️ Défense | Ce que l'adversaire concède à son poste, avec le rang sur 30 |
| ⚡ Rythme | Possessions attendues, temps de jeu récent |
| 📐 Type de shoot | Volume et réussite à 2 pts, 3 pts, lancers |
| 📊 Carrière | Moyennes saison par saison |

Plus : la liste du soir triable, les absences avec « qui prend le relais »,
une page **Défense vs poste** pour les 30 équipes, et une **ligne modifiable** sur chaque fiche
(tous les pourcentages se recalculent).

**Coût : 0 €.** Données ESPN publiques, calculs et hébergement sur GitHub (gratuit pour un dépôt public).

---

## Mise en ligne (15 minutes, sans coder)

1. **Crée un compte** sur [github.com](https://github.com) (gratuit).
2. **Nouveau dépôt** : bouton « + » en haut à droite → *New repository* → nomme-le `matchup`,
   coche **Public** → *Create repository*.
3. **Envoie les fichiers** : sur la page du dépôt, *uploading an existing file*, puis
   glisse-dépose tout le contenu du dossier décompressé → *Commit changes*.
   > ⚠️ Le dossier caché `.github` ne passe parfois pas au glisser-déposer. Vérifie qu'il apparaît.
   > Sinon : *Add file → Create new file*, tape le nom `.github/workflows/update.yml`,
   > colle le contenu du fichier du même nom, puis *Commit*.
4. **Autorise les mises à jour** : *Settings → Actions → General* → tout en bas,
   *Workflow permissions* → **Read and write permissions** → *Save*.
5. **Active le site** : *Settings → Pages* → *Source* : **GitHub Actions**.
6. **Premier lancement** : onglet *Actions* → *Mise à jour des données* → **Run workflow**.
   Le premier passage télécharge 3 saisons d'historique : compte **30 à 60 minutes**.
   Les suivants prennent 1 à 2 minutes.
7. Ton site est en ligne sur **`https://TON-PSEUDO.github.io/matchup/`**.
   Sur téléphone : ouvre-le puis *Partager → Sur l'écran d'accueil* pour l'avoir comme une appli.

Ensuite tout est automatique : mise à jour toutes les 3 h, et toutes les 30 min
les soirs de match (absences relues à chaque passage).

---

## Option : vraies lignes des bookmakers (gratuit aussi)

Sans clé, la ligne par défaut est la moyenne du joueur arrondie (x,5), et tu peux la modifier
sur chaque fiche. Pour avoir la vraie ligne d'avant-match :

1. Crée une clé gratuite sur [the-odds-api.com](https://the-odds-api.com) (500 crédits/mois).
2. Dans ton dépôt : *Settings → Secrets and variables → Actions → New repository secret*,
   nom **`ODDS_API_KEY`**, valeur = ta clé.

Par défaut seules les lignes **points** sont récupérées, une fois par jour
(~10 crédits par soirée, donc ça tient dans le gratuit). Pour plus de marchés, ajoute une
*variable* (onglet *Variables*) `ODDS_MARKETS`, par ex. `player_points,player_rebounds`
— chaque marché ajouté multiplie la consommation.

Les lignes sont archivées jour après jour : avec le temps, les H2H et la forme sont jugés
contre la **vraie ligne de chaque soir** (marqueur ● orange).

---

## Réglages

| Variable (onglet *Variables*) | Défaut | Rôle |
|---|---|---|
| `HISTORY_SEASONS` | `2` | Saisons passées gardées pour H2H et styles |
| `ODDS_MARKETS` | `player_points` | Marchés de lignes récupérés |

## Comment ça marche

```
scripts/fetch.py     → télécharge calendrier, box scores, blessures (ESPN) et lignes → data/
scripts/analyze.py   → calcule défense vs poste, rythme, styles, H2H, avec/sans… → site/data/
site/                → le site (HTML/CSS/JS, aucun serveur)
scripts/mock_data.py → données fictives pour tester hors connexion
```

Tester sur ton ordinateur (Python 3.10+, rien à installer) :

```bash
python scripts/fetch.py && python scripts/analyze.py
cd site && python -m http.server 8000      # puis http://localhost:8000
```

### Méthode (en bref)
- **Défense vs poste** : production des adversaires par poste (meneurs/arrières, ailiers, pivots),
  ramenée à la minute jouée et comparée à la moyenne NBA. En début de saison, la saison
  précédente compte encore un peu (son poids baisse jusqu'au 20ᵉ match).
- **Profil défensif** : « Mur intérieur », « Verrou à 3 pts », « Anti-meneurs », « Passoire »…
  selon l'écart le plus marqué de l'équipe.
- **Style de joueur** : déduit des chiffres par 36 min (tirs à 3, passes, rebonds, contres, lancers).
- **Rythme** : possessions ≈ tirs tentés + 0,44 × lancers − rebonds off. + pertes de balle.
- **Avec / sans** : matchs de la même équipe où le coéquipier était présent vs absent.

### Limites honnêtes
- Les endpoints ESPN sont publics mais non officiels : s'ils changent, le script peut casser
  (les erreurs apparaissent dans l'onglet *Actions*).
- Les « duels » joueur contre défenseur direct du site d'origine demandent des données
  de suivi payantes : non inclus.
- Analyse statistique, **pas un pronostic**. 18+ · Jouer comporte des risques :
  Joueurs Info Service 09 74 75 13 13.

---

## Tennis (onglet « Tennis »)

Programme du jour ATP et WTA, avec pour chaque match :
- **Probabilité de victoire** : Elo global + Elo par surface (dur, terre, gazon), ajustée par l'archétype et la fatigue.
- **Styles de jeu** : 8 archétypes (gros serveur, serveur-cogneur, attaquant de fond de court, frappeur à plat,
  contre-attaquant, terrien lifteur, joueur complet, créatif) attribués à 272 des 300 meilleurs joueurs et joueuses
  (`data/tennis_styles.json`, sources dans `data/tennis_styles_sources.tsv`). Liste à rafraîchir tous les 2-3 mois.
- **Insight d'archétype** : bilan d'un style contre l'autre, calculé sur tout l'historique.
- **Face à face, forme, fatigue**, et **value signals** (Slight ≥ 8 %, Moderate ≥ 15 %, Strong ≥ 25 %) si la clé
  The Odds API est configurée. Les cotes tennis sont relevées une fois par jour pour préserver le quota gratuit.

Limites : pas de Challengers ni de vitesse des courts (données payantes) ; historique depuis janvier 2024.
