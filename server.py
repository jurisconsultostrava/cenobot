#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FEED SERVER — vystaví vygenerovaný XML feed na URL, aby si ho Shoptet
Automatický import mohl stahovat. Zároveň feed pravidelně regeneruje.

Endpointy:
  GET /ceny.xml         → aktuální feed (Shoptet si sem nastaví import)
  GET /health           → stav (poslední regenerace, počet položek)
  GET /regenerate?key=  → ruční regenerace (chráněno FEED_TOKEN)

Regenerace běží na pozadí každých INTERVAL_MIN minut v obchodní době.
Určeno pro Railway/VPS. Start: python3 server.py
"""
import os, threading, time, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import generuj_feed as gf

PORT = int(os.environ.get("PORT", "8080"))
INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "15"))
FEED_TOKEN = os.environ.get("FEED_TOKEN", "")
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Prague"))
OPEN_H = int(os.environ.get("MARKET_OPEN_HOUR", "8"))
CLOSE_H = int(os.environ.get("MARKET_CLOSE_HOUR", "22"))
FEED_PATH = gf.FEED_PATH

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] server: %(message)s")
log = logging.getLogger("server")
_state = {"last_run": None, "count": 0}


def market_open(now):
    return now.weekday() < 5 and OPEN_H <= now.hour < CLOSE_H


def regen_loop():
    while True:
        now = datetime.now(TZ)
        if market_open(now):
            try:
                n = gf.run()
                _state["last_run"] = now.isoformat()
                _state["count"] = n
            except Exception as e:
                log.exception("Regenerace selhala: %s", e)
        else:
            log.info("Mimo obchodní okno (%s) — přeskakuji.", now.strftime("%a %H:%M"))
        time.sleep(INTERVAL_MIN * 60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # ticho

    def do_GET(self):
        if self.path.startswith("/ceny.xml"):
            if FEED_PATH.exists():
                data = FEED_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(503, "Feed zatim nevygenerovan")
        elif self.path.startswith("/health"):
            import json
            body = json.dumps(_state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/regenerate"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            if FEED_TOKEN and q.get("key", [""])[0] != FEED_TOKEN:
                self.send_error(403, "Spatny token"); return
            n = gf.run()
            self.send_response(200); self.end_headers()
            self.wfile.write(f"Regenerovano: {n} polozek".encode())
        else:
            self.send_error(404)


def main():
    log.info("Feed server start | port %d | interval %d min | okno %d-%d",
             PORT, INTERVAL_MIN, OPEN_H, CLOSE_H)
    threading.Thread(target=regen_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
