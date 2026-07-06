# CENOBOT — automatický přepočet cen pro moje-zlato.cz (Shoptet)

Systém stáhne živé ceny ze StoneX, vygeneruje Shoptet XML feed a vystaví ho
na URL. Shoptet Automatický import si feed sám stahuje a přeceňuje produkty.

## Architektura (celá ověřená z dokumentace)

```
[StoneX gross_price] ──curl_cffi──> [cenobot generuje XML feed]
   API vrací HOTOVOU cenu           spáruje přes part_number==code,
   + part_number (=váš kód)         převede EUR→CZK, přidá marži
                                            │
                                            ▼
                          [feed na URL: https://váš-server/ceny.xml]
                                            │
                                            ▼
            [Shoptet Automatický import] ──sám stahuje z URL──>
               páruje přes KÓD, aktualizuje JEN cenu, až 16×/den
```

**Klíčové:** StoneX vrací hotovou cenu (`gross_price`), nepočítá se nic ze
spotu → záměna kovu nemožná. Zápis dělá Shoptet přes XML import, ne my.

## Tři principy (dle zadání)

1. **Párování výhradně přes KÓD.** Feed obsahuje `<CODE>` a `<PRICE>`.
   Shoptet import se nastaví na párování podle kódu. StoneX `part_number`
   = váš Shoptet kód (ověřeno: 3002071, 3002310, 3002329).
2. **Zápis přes XML feed + Automatický import** (Shoptet nemá REST API pro
   zápis cen — má XML import, což je nativní a robustní cesta).
3. **Automatika.** Server regeneruje feed každých 15 min; Shoptet si ho
   stahuje sám dle svého rozvrhu (až 16× denně dle tarifu).

## Bezpečnostní pojistky

- **ČNB se do feedu nezařadí** (28 produktů `skip=True`) → Shoptet je nepřepíše.
- **Feed obsahuje jen CODE + PRICE + CURRENCY** — žádné prázdné elementy.
  (Prázdný element by Shoptet interpretoval jako "smaž hodnotu".)
- **Sanity-check.** Cena mimo ±15 % proti poslední se do feedu nedá a zaloguje.
- **Fail-safe.** Když StoneX nevrátí ceny, feed se NEPŘEPÍŠE — zůstane poslední
  platný. Shoptet tak nikdy nedostane prázdný nebo chybný feed.

## Instalace

```bash
pip install -r requirements.txt   # curl_cffi
```

## Konfigurace (proměnné prostředí)

| Proměnná | Popis | Výchozí |
|---|---|---|
| `FX_CZK_EUR` | kurz CZK za 1 EUR | 24.183 |
| `FX_API_URL` | živý zdroj kurzu `{"czk_eur":..}` (volitelné) | — |
| `MARZE_PCT` | marže nad StoneX cenou (%) | 1.25 |
| `MAX_ZMENA_PCT` | max povolený skok ceny (%) | 15 |
| `INTERVAL_MIN` | interval regenerace feedu (min) | 15 |
| `MARKET_OPEN_HOUR`/`CLOSE_HOUR` | obchodní okno | 8 / 22 |
| `FEED_OUTPUT` | cesta k souboru feedu | ceny_feed.xml |
| `FEED_TOKEN` | token pro ruční /regenerate (volitelné) | — |
| `PORT` | port serveru | 8080 |

## Spuštění

```bash
python3 src/generuj_feed.py     # jednorázově vygeneruje feed
python3 server.py               # server: vystaví feed + regeneruje
```

Feed pak běží na `http://váš-server:PORT/ceny.xml`.

## Nasazení na Railway
1. Nahraj složku do Git repa.
2. Railway → Deploy from repo.
3. Variables: `FX_CZK_EUR` (nebo `FX_API_URL`), `MARZE_PCT`.
4. Start command: `python3 server.py`.
5. Railway přidělí veřejnou URL — feed bude na `https://…railway.app/ceny.xml`.
   POZOR: ověř v logu, že první stažení ze StoneX projde (curl_cffi obchází
   Cloudflare, ale Railway IP musí být průchozí).

## Nastavení v Shoptet administraci (JEDNORÁZOVĚ)

1. **Produkty → Automatické importy → Přidat import.**
2. Zadej: jméno importu, importní kód, **XML URL** = adresa tvého feedu
   (`https://…/ceny.xml`).
3. Klikni **Validovat** — feed musí projít (má strukturu dle
   products-supplier-v10.rng).
4. **Párovat produkty podle: Kód produktu.**
5. **Položky importu:** zaškrtni POUZE **Cena**. Nic jiného — aby se
   nepřepisovaly názvy, obrázky, popisy.
6. **Cenový koeficient:** nech 1 (marže už je ve feedu). NEBO dej marži sem
   a v cenobotu nastav MARZE_PCT=0 — jedno nebo druhé, ne obojí.
7. **Produkty chybějící ve feedu:** "Ponechat nezměněné" (ČNB a historické
   mince nejsou ve feedu a musí zůstat beze změny).
8. **Rozvrh:** aktualizační import, nastav četnost dle tarifu (až 16×/den).

## Databáze produktů (src/products_db.json)
Mapa `kód → {name, guid, metal, skip}`, 316 produktů, 28 ČNB chráněno.
`skip=True` = ČNB, do feedu se nezařadí. Nový produkt = přidej řádek s kódem.

## Co systém NEřeší
- ČNB a historické mince bez StoneX protějšku (~46): StoneX je neprodává.
  Zůstávají na ručně zadané ceně, feed se jich nedotýká.
- Šperky, certifikáty: nemají StoneX cenu.
