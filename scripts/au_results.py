#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
au_results.py — flux de la v5 de LOTTO AI AU : au_results.json (08/10/2026)

  powerball : 30 derniers tirages (7 numéros 1-35 + Powerball 1-20) + vrai dividende par gagnant
              pour chaque division (« 7+PB », « 7 », « 6+PB », « 6 », « 5+PB », « 4+PB », « 5 »,
              « 3+PB », « 2+PB ») et nombre de gagnants (Australie entière).
  ozlotto   : 30 derniers tirages (7 numéros 1-47 + 3 supplémentaires) + dividendes des 7 divisions
              (« 7 », « 6+S », « 6 », « 5+S », « 5 », « 4 », « 3+S »).
  next      : prochain tirage annoncé par Lotterywest (date AEST) — tient compte des tirages déplacés.

Sources :
  • API OFFICIELLE Lotterywest api.lotterywest.wa.gov.au/api/v1/games (10 derniers tirages, dividendes
    nationaux « each » + gagnants « winners »).
  • Historique : lotto.net, page de chaque tirage (« Prize Breakdown ») pour compléter jusqu'à 30.
  Sur les tirages présents dans les deux sources, numéros ET dividendes doivent concorder (sinon échec).
Fusion avec le fichier déjà publié ; échec bruyant si le flux est périmé (> 9 j, 1 tirage/semaine).
Le flux de la v4 (aulotto_recent.json, update_aulotto.py) n'est PAS touché.
Local (DNS détourné) : AU_RESOLVE="host:443:ip,host:443:ip" pour forcer les IP.
"""
import json, os, re, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone

FEED = "au_results.json"
KEEP = 30
MAX_STALE_DAYS = 9
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
LW = "https://api.lotterywest.wa.gov.au/api/v1/games"
GAMES = {
    "powerball": {"id": "5132", "net": "australia-powerball", "pool": 35, "bonus": 20,
                  "keys": ["7+PB", "7", "6+PB", "6", "5+PB", "4+PB", "5", "3+PB", "2+PB"],
                  "matrix": [[7, 1], [7, 0], [6, 1], [6, 0], [5, 1], [4, 1], [5, 0], [3, 1], [2, 1]],
                  "net_labels": ["Match 7 + Powerball", "Match 7", "Match 6 + Powerball", "Match 6",
                                 "Match 5 + Powerball", "Match 4 + Powerball", "Match 5",
                                 "Match 3 + Powerball", "Match 2 + Powerball"]},
    "ozlotto": {"id": "5130", "net": "oz-lotto", "pool": 47, "bonus": 47,
                "keys": ["7", "6+S", "6", "5+S", "5", "4", "3+S"],
                "matrix": [[7, 0], [6, 1], [6, 0], [5, 1], [5, 0], [4, 0], [3, 1]],
                "net_labels": None},
}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def curl(url, timeout=60):
    extra = []
    for r in filter(None, os.environ.get("AU_RESOLVE", "").split(",")):
        extra += ["--resolve", r]
    r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA] + extra + [url],
                       capture_output=True, text=True, timeout=timeout + 30)
    return r.stdout if r.returncode == 0 else ""


def money(s):
    v = float(str(s).replace("$", "").replace(",", "").strip() or 0)
    return v if v > 0 else None


def check(game, d, nums, bonus):
    g = GAMES[game]
    nb = 1 if game == "powerball" else 3
    if len(set(nums)) != 7 or not all(1 <= n <= g["pool"] for n in nums) \
            or len(bonus) != nb or not all(1 <= b <= g["bonus"] for b in bonus) \
            or (game == "ozlotto" and (len(set(bonus)) != 3 or set(bonus) & set(nums))):
        raise SystemExit(f"{game} {d}: valeurs invalides {nums} + {bonus}")


# ----------------------------- Lotterywest (officiel) -----------------------------

def lotterywest():
    for i in range(4):
        body = curl(LW)
        try:
            data = json.loads(body)["data"]
            break
        except Exception:
            print(f"  Lotterywest essai {i + 1} KO", file=sys.stderr); time.sleep(10 * (i + 1))
    else:
        raise SystemExit("Lotterywest injoignable")
    out, nxt = {}, {}
    for game, g in GAMES.items():
        gd = data[g["id"]]
        if gd["upcoming_draw"]["division_matrix"] != g["matrix"]:
            raise SystemExit(f"{game}: divisions changées {gd['upcoming_draw']['division_matrix']}")
        # draw_close = fin des ventes WA, le soir du tirage → date du tirage en heure AEST (UTC+10)
        close = datetime.fromisoformat(gd["upcoming_draw"]["draw_close"].replace("Z", "+00:00"))
        nxt[game] = (close + timedelta(hours=10)).date().isoformat()
        rows = []
        for r in gd["results"]:
            nums = sorted(int(v) for v in r["winning_numbers"].values())
            bonus = [int(v) for v in r["supplementary_numbers"].values()]
            bonus = bonus if game == "powerball" else sorted(bonus)
            check(game, r["draw_date"], nums, bonus)
            pay, win = {}, {}
            for k, (key) in enumerate(g["keys"], 1):
                dv = r["divisions"][str(k)]
                win[key] = int(dv["winners"])
                v = money(dv["each"])
                if v is not None and win[key] > 0:
                    pay[key] = v
            row = {"date": r["draw_date"], "draw": int(r["draw_num"]), "numbers": nums,
                   ("powerball" if game == "powerball" else "supps"): (bonus[0] if game == "powerball" else bonus),
                   "payouts": pay, "winners": win}
            rows.append(row)
        out[game] = rows
    return out, nxt


# ----------------------------- lotto.net (historique) -----------------------------

def net_dates(game, year):
    html = curl(f"https://www.lotto.net/{GAMES[game]['net']}/results/{year}")
    ds = set()
    for m, d, y in re.findall(r'/results/([a-z]+)-(\d{2})-(\d{4})"', html):
        if m in MONTHS:
            ds.add(f"{y}-{MONTHS.index(m) + 1:02d}-{d}")
    return ds


def net_draw(game, iso):
    y, m, d = iso.split("-")
    html = curl(f"https://www.lotto.net/{GAMES[game]['net']}/results/{MONTHS[int(m) - 1]}-{d}-{y}")
    if "Prize Breakdown" not in html:
        return None
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t); t = re.sub(r"\s+", " ", t)
    head = t[t.find("Draw Date"):t.find("Prize Breakdown")]
    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", head.split(y, 1)[-1])]
    if game == "powerball":
        main, bonus = sorted(nums[:7]), nums[7:8]
    else:
        main, bonus = sorted(nums[:7]), sorted(nums[7:10])
    check(game, iso, main, bonus)
    block = t[t.find("Prize Breakdown"):t.find("Totals", t.find("Prize Breakdown"))]
    rows = re.findall(r"(Match [0-9][^$]*?) \$([\d,.]+)(?: Rollover!)? ([\d,]+) \$([\d,.]+)", block)
    g = GAMES[game]
    if len(rows) != len(g["keys"]):
        raise SystemExit(f"{game} {iso}: {len(rows)} divisions lues sur lotto.net")
    pay, win = {}, {}
    for key, (label, each, winners, _) in zip(g["keys"], rows):
        win[key] = int(winners.replace(",", ""))
        v = money(each)
        if v is not None and win[key] > 0:
            pay[key] = v
    dn = re.search(r"Draw Number: ([\d,]+)", t)
    return {"date": iso, "draw": int(dn.group(1).replace(",", "")) if dn else None, "numbers": main,
            ("powerball" if game == "powerball" else "supps"): (bonus[0] if game == "powerball" else bonus),
            "payouts": pay, "winners": win}


def main():
    prev = {}
    if os.path.exists(FEED):
        try:
            prev = json.load(open(FEED))
        except Exception as e:
            print("flux existant illisible:", e, file=sys.stderr)
    lw, nxt = lotterywest()
    new = {}
    for game in GAMES:
        by = {r["date"]: r for r in prev.get(game, [])}
        for r in lw[game]:
            by[r["date"]] = r
        # Complément historique (lotto.net) jusqu'à KEEP tirages
        if len(by) < KEEP:
            today = date.today()
            ds = net_dates(game, today.year) | (net_dates(game, today.year - 1) if today.month <= 8 else set())
            for iso in sorted(ds, reverse=True)[:KEEP + 2]:
                if iso in by and iso not in {r["date"] for r in lw[game]}:
                    continue
                time.sleep(1.5)
                got = net_draw(game, iso)
                if not got:
                    continue
                if iso in by:   # recoupement avec l'officiel
                    o = by[iso]
                    keyb = "powerball" if game == "powerball" else "supps"
                    if o["numbers"] != got["numbers"] or o[keyb] != got[keyb] or o["payouts"] != got["payouts"]:
                        raise SystemExit(f"{game} {iso}: Lotterywest ≠ lotto.net\n{o}\n{got}")
                    continue
                by[iso] = got
        lst = sorted(by.values(), key=lambda x: x["date"], reverse=True)[:KEEP]
        if len(lst) < 8:
            raise SystemExit(f"FAIL: {game} seulement {len(lst)} tirages")
        age = (date.today() - date.fromisoformat(lst[0]["date"])).days
        print(f"{game}: {len(lst)} tirages, dernier {lst[0]['date']} ({age} j), prochain {nxt[game]}", file=sys.stderr)
        if age > MAX_STALE_DAYS:
            raise SystemExit(f"FAIL: {game} périmé")
        new[game] = lst
    new["next"] = nxt
    if new == {k: prev.get(k) for k in new}:
        print("Aucune nouvelle donnée.", file=sys.stderr); return
    json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **new},
              open(FEED, "w"), ensure_ascii=False, indent=1)
    print("OK", file=sys.stderr)


if __name__ == "__main__":
    main()
