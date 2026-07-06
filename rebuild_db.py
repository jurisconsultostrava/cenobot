#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REBUILD DB — aktualizuje StoneX prémie v products_db.json z nového PDF katalogu.
Kov, hmotnost a GUID zůstávají (ty se nemění); mění se jen premium_eur/pct.
Vstup: stonex_catalog.json (název -> [premie_eur, pct, hmotnost_g]),
       vytvořený přepisem WE SELL sloupce z aktuálního StoneX PDF.

Použití: python3 rebuild_db.py
P�rování probíhá JEDNORÁZOVĚ a člověk ho může zkontrolovat v reportu.
Za běhu (cenobot.py) se už páruje výhradně přes kód — tady se jen
obnovují prémie u existujících kódů.
"""
import json, re, unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "products_db.json"
CAT = BASE / "stonex_catalog.json"

def fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def metal_sx(name):
    n = fold(name)
    if "pallad" in n: return "pd"
    if "platin" in n: return "pt"
    if "silver" in n: return "ag"
    return "au"

def toks(s):
    s = fold(s).replace("|", " ")
    s = s.replace("argor-heraeus", "argorheraeus").replace("argor heraeus", "argorheraeus")
    s = s.replace("year of the horse", "yoth").replace("rok kone", "yoth")
    s = s.replace("wiener philharmoniker", "vienna").replace("philharmoniker", "vienna").replace("philharmonic", "vienna")
    for w in ("zlaty","gold","stribrny","stribrna","silver","platinovy","platinova","platinum","investicni"):
        s = s.replace(w, "")
    s = s.replace("slitek", "bar").replace("mince", "coin")
    s = s.replace("munze osterreich", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return set(w for w in s.split() if len(w) > 1)

def main():
    db = json.loads(DB.read_text(encoding="utf-8"))
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    sx = [(name, prem, metal_sx(name), prem[2], toks(name)) for name, prem in cat.items()]

    updated = 0
    for code, rec in db.items():
        if rec.get("skip"):
            continue
        cz_t = toks(rec["name"]); cz_m = rec["metal"]; cz_w = rec.get("weight_g")
        best = None; bs = 0
        for name, prem, m_m, m_w, m_t in sx:
            if cz_m != m_m:
                continue
            if cz_w and m_w and abs(cz_w - m_w) / max(cz_w, m_w) > 0.02:
                continue
            inter = len(cz_t & m_t); union = len(cz_t | m_t)
            j = inter / union if union else 0
            exact = cz_w and m_w and abs(cz_w - m_w) / max(cz_w, m_w) < 0.02
            score = j + (0.3 if exact else 0)
            if score > bs:
                bs = score; best = (name, prem)
        if best and bs >= 0.38:
            rec["stonex"] = {"item": best[0], "premium_eur": best[1][0],
                             "premium_pct": best[1][1], "weight_g": best[1][2]}
            updated += 1
    DB.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Prémie aktualizovány u {updated} produktů.")

if __name__ == "__main__":
    main()
