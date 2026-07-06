#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CENOBOT — generátor Shoptet XML feedu s aktuálními cenami

ARCHITEKTURA (ověřená z dokumentace Shoptet):
  [StoneX gross_price přes curl_cffi]
     -> spáruj přes part_number==code, převeď EUR->CZK, přidej marži
     -> vygeneruj VALIDNÍ Shoptet XML feed (dle products-supplier-v10.rng)
     -> feed vystav na URL
  [Shoptet Automatický import] si feed sám stáhne, spáruje přes KÓD,
     aktualizuje JEN cenu, až 16x denně. (Zápis NEřešíme my — dělá Shoptet.)

STRUKTURA FEEDU (dle oficiálního vzoru VariantItem.xml):
  <SHOP><SHOPITEM><CODE>..</CODE><CURRENCY>CZK</CURRENCY>
  <PRICE>..</PRICE></SHOPITEM>...</SHOP>
  → jen CODE + PRICE. Žádné prázdné elementy (ty by Shoptet vymazal).

PRINCIPY:
  1) Párování jen přes kód (CODE = StoneX part_number). Nastaví se i v Shoptetu.
  2) Zápis přes XML feed + Automatický import (ne přes API — to Shoptet nemá).
  3) Automatika: Shoptet stahuje feed sám v intervalu. Tento skript jen
     feed pravidelně regeneruje (cron/scheduler na serveru).

BEZPEČNOST:
  - ČNB se do feedu NEZAŘADÍ (skip=True) → Shoptet je nepřepíše.
  - Sanity-check: cenu mimo rozsah proti referenci vynechá.
  - Když StoneX nevrátí ceny, feed se NEPŘEPÍŠE (zachová poslední platný).
"""
import os, sys, json, time, logging
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None
import urllib.request, urllib.error

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "products_db.json"
FEED_PATH = Path(os.environ.get("FEED_OUTPUT", BASE.parent / "ceny_feed.xml"))

STONEX_URL = "https://stonexbullion.com/api/client/catalog"
STONEX_PAGES = int(os.environ.get("STONEX_MAX_PAGES", "30"))
MARZE_PCT = float(os.environ.get("MARZE_PCT", "1.25"))
KURZ_CZK_EUR = float(os.environ.get("FX_CZK_EUR", "24.183"))
FX_API_URL = os.environ.get("FX_API_URL", "")
MAX_ZMENA_PCT = float(os.environ.get("MAX_ZMENA_PCT", "15"))

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("cenobot")


def fetch_stonex():
    """{part_number: gross_price_eur} ze StoneX přes curl_cffi (obchází Cloudflare)."""
    if cffi_requests is None:
        log.error("curl_cffi není nainstalováno: pip install curl_cffi"); return {}
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://stonexbullion.com/",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    ceny = {}
    for page in range(1, STONEX_PAGES + 1):
        try:
            r = cffi_requests.post(f"{STONEX_URL}?page={page}", headers=headers,
                                   json={}, impersonate="chrome120", timeout=30)
        except Exception as e:
            log.error("StoneX page %d: %s", page, e); break
        if r.status_code != 200:
            log.error("StoneX page %d: HTTP %s", page, r.status_code); break
        try:
            cat = r.json().get("data", {}).get("catalog", {})
            products = cat.get("products", [])
            last_page = cat.get("paginator", {}).get("last_page", page)
        except Exception as e:
            log.error("StoneX page %d JSON: %s", page, e); break
        if not products: break
        for p in products:
            pn = str(p.get("part_number", "")).strip()
            gp = p.get("gross_price")
            if pn and gp is not None:
                ceny[pn] = float(gp)
        log.info("StoneX page %d/%s: %d (celkem %d)", page, last_page, len(products), len(ceny))
        if page >= last_page: break
        time.sleep(0.4)
    return ceny


def load_fx():
    if FX_API_URL:
        try:
            with urllib.request.urlopen(FX_API_URL, timeout=15) as r:
                d = json.loads(r.read().decode())
                if "czk_eur" in d: return float(d["czk_eur"])
        except Exception as e:
            log.warning("FX_API selhalo (%s) — fallback %.3f", e, KURZ_CZK_EUR)
    return KURZ_CZK_EUR


def build_feed(prices):
    """Vytvoří validní Shoptet XML feed. prices: [(code, price_czk)]."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<SHOP>"]
    for code, price in prices:
        lines.append("  <SHOPITEM>")
        lines.append(f"    <CODE>{escape(str(code))}</CODE>")
        lines.append("    <CURRENCY>CZK</CURRENCY>")
        lines.append(f"    <PRICE>{price:.2f}</PRICE>")
        lines.append("  </SHOPITEM>")
    lines.append("</SHOP>")
    return "\n".join(lines)


def run():
    log.info("=== CENOBOT feed start %s ===", datetime.now(timezone.utc).isoformat())
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    fx = load_fx()
    log.info("Kurz CZK/EUR: %.3f | marže %.2f%%", fx, MARZE_PCT)
    stonex = fetch_stonex()
    if not stonex:
        log.error("StoneX nevrátil ceny — feed NEPŘEPISUJI (zachovávám poslední).")
        return 0
    log.info("StoneX vrátil %d cen.", len(stonex))

    prices, skip_cnb, no_match, sanity = [], 0, 0, 0
    for code, rec in db.items():
        if rec.get("skip"):
            skip_cnb += 1; continue
        gross = stonex.get(code)          # PÁROVÁNÍ VÝHRADNĚ PŘES KÓD
        if gross is None:
            no_match += 1; continue
        prodej = round(gross * fx * (1 + MARZE_PCT / 100), 2)
        ref = rec.get("last_price")
        if ref:
            z = abs(prodej - ref) / ref * 100
            if z > MAX_ZMENA_PCT:
                sanity += 1
                log.warning("SANITY skip %s: %s->%s (%.1f%%) | %s",
                            code, ref, prodej, z, rec["name"][:38])
                continue
        rec["last_price"] = prodej
        prices.append((code, prodej))

    log.info("Feed: %d cen | ČNB skip %d | bez shody %d | sanity %d",
             len(prices), skip_cnb, no_match, sanity)
    if not prices:
        log.error("Žádné ceny — feed nepřepisuji."); return 0

    FEED_PATH.write_text(build_feed(prices), encoding="utf-8")
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Feed zapsán: %s (%d položek)", FEED_PATH, len(prices))
    log.info("=== CENOBOT feed konec ===")
    return len(prices)


if __name__ == "__main__":
    run()
