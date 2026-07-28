#!/usr/bin/env python3
"""
update_aulotto.py — régénère aulotto_recent.json depuis l'API officielle Lotterywest.

Tourne dans une GitHub Action (runners US : PAS de blocage DNS ni géo-fence).
L'app iOS lit le JSON via raw.githubusercontent.com (fiable partout).

⚠️ LEÇON UK : toute panne doit être BRUYANTE (exit 1) — jamais de succès silencieux
qui laisse un flux gelé pendant des semaines.
"""
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta

API = "https://api.lotterywest.wa.gov.au/api/v1/games"
GAMES = {"5132": ("powerball", 35, 20, 1), "5130": ("ozlotto", 47, 47, 3)}  # id -> (clé, pool_m, pool_s, n_supp)
OUT = "aulotto_recent.json"
MAX_STALE_DAYS = 9   # chaque jeu tire 1×/semaine : au-delà de 9 j sans tirage = flux malade


def fail(msg):
    print(f"ERREUR: {msg}", file=sys.stderr)
    sys.exit(1)


req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
except Exception as e:
    fail(f"API Lotterywest injoignable: {e}")

data = payload.get("data", payload)
out = {}
for gid, (key, pool_m, pool_s, n_supp) in GAMES.items():
    game = data.get(gid)
    if not game or not game.get("results"):
        fail(f"jeu {gid} absent/vide dans la réponse API")
    rows = []
    for res in game["results"]:
        try:
            draw_no = int(res["draw_num"])
            d = datetime.strptime(res["draw_date"][:10], "%Y-%m-%d").date()
            mains = sorted(int(v) for v in res["winning_numbers"].values())
            supps = sorted(int(v) for v in res["supplementary_numbers"].values())
        except Exception as e:
            fail(f"{key}: ligne illisible ({e}): {res}")
        if len(mains) != 7 or len(supps) != n_supp:
            fail(f"{key} draw {draw_no}: {len(mains)} mains + {len(supps)} supp (attendu 7+{n_supp})")
        if not all(1 <= n <= pool_m for n in mains) or not all(1 <= n <= pool_s for n in supps):
            fail(f"{key} draw {draw_no}: numéro hors pool {mains}/{supps}")
        if len(set(mains)) != 7:
            fail(f"{key} draw {draw_no}: doublon mains {mains}")
        rows.append({"date": d.isoformat(), "draw": draw_no, "main": mains, "special": supps})
    rows.sort(key=lambda r: -r["draw"])
    newest = datetime.strptime(rows[0]["date"], "%Y-%m-%d").date()
    if (date.today() - newest).days > MAX_STALE_DAYS:
        fail(f"{key}: dernier tirage {newest} = trop vieux (> {MAX_STALE_DAYS} j) — flux gelé ?")
    out[key] = rows
    print(f"{key}: {len(rows)} tirages, dernier draw {rows[0]['draw']} du {rows[0]['date']}")

with open(OUT, "w") as f:
    json.dump(out, f, indent=1)
print(f"OK -> {OUT}")
