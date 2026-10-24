"""Live market data from free, keyless public APIs, reported in Canadian dollars.

- TSX-listed stocks and ETFs: TMX Money (prices in CAD).
- US-listed stocks and ETFs: Nasdaq's quote API (USD, may be delayed ~15 minutes), converted to CAD.
- Crypto: CoinGecko, priced directly in CAD.
- USD/CAD exchange rate: Coinbase's live rate (refreshed every minute), falling back to the Bank of Canada's daily rate.
- Government of Canada bond / T-bill yields: Bank of Canada Valet API.

Symbols are keyed by market: ``tsx:XEQT``, ``us:AAPL`` (or a bare ``AAPL``), ``crypto:BTC``.
Results are cached in memory so the page can refresh often without hammering the sources.
"""

import datetime as dt
import json
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import certifi

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
QUOTE_TTL = 60  # seconds
RATES_TTL = 60 * 60
VALET = "https://www.bankofcanada.ca/valet/observations"
TMX_QUERY = (
    "query getQuoteBySymbol($symbol: String, $locale: String) {"
    " getQuoteBySymbol(symbol: $symbol, locale: $locale) { symbol name price priceChange percentChange exchangeName } }"
)

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _get(url: str, timeout: float = 10, body: dict | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return resp.read()


def _cached(key: str, ttl: float) -> dict | None:
    with _lock:
        hit = _cache.get(key)
    return hit[1] if hit and time.time() - hit[0] < ttl else None


def _store(key: str, value: dict) -> dict:
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", "").replace("+", ""))
    except ValueError:
        return None


def _clean_name(name: str | None) -> str | None:
    """'Apple Inc. Common Stock' -> 'Apple Inc.'"""
    if not name:
        return name
    return re.sub(
        r"\s+(Class [A-Z]\s+)?(Common Stock|Ordinary Shares|Capital Stock|American Depositary Shares"
        r"|Subordinate Voting Shares|Limited Voting Shares).*$",
        "",
        name,
    )


# ---------- Exchange rate ----------

def get_usd_cad() -> dict:
    """USD -> CAD rate, e.g. {"rate": 1.4064, "asOf": "2026-10-20 21:23", "live": True, "source": "Coinbase"}.

    Uses Coinbase's live rate (cached for a minute, like stock quotes). If that's unreachable,
    falls back to the Bank of Canada's daily average rate.
    """
    if hit := _cached("fx-live", QUOTE_TTL):
        return hit
    try:
        rate = float(json.loads(_get("https://api.coinbase.com/v2/exchange-rates?currency=USD"))["data"]["rates"]["CAD"])
        return _store("fx-live", {
            "rate": rate,
            "asOf": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "live": True,
            "source": "Coinbase",
        })
    except Exception:
        pass
    if hit := _cached("fx-boc", RATES_TTL):
        return hit
    try:
        obs = json.loads(_get(f"{VALET}/FXUSDCAD/json?recent=1"))["observations"][0]
        return _store("fx-boc", {"rate": float(obs["FXUSDCAD"]["v"]), "asOf": obs["d"], "live": False, "source": "Bank of Canada daily rate"})
    except Exception:
        return {"error": "USD/CAD rate unavailable"}


# ---------- Quotes ----------

def _tmx_quote(symbol: str) -> dict:
    key = "tsx:" + symbol
    if hit := _cached(key, QUOTE_TTL):
        return hit
    try:
        data = json.loads(_get(
            "https://app-money.tmx.com/graphql",
            body={"operationName": "getQuoteBySymbol", "variables": {"symbol": symbol, "locale": "en"}, "query": TMX_QUERY},
            headers={"Content-Type": "application/json", "Origin": "https://money.tmx.com", "Referer": "https://money.tmx.com/"},
        ))
        q = (data.get("data") or {}).get("getQuoteBySymbol") or {}
    except Exception:
        q = {}
    price = _num(q.get("price"))
    if price is None:
        return {"error": "Symbol not found on the TSX"}
    return _store(key, {
        "price": price,
        "currency": "CAD",
        "change": _num(q.get("priceChange")),
        "changePct": _num(q.get("percentChange")),
        "name": _clean_name(q.get("name")),
        "exchange": q.get("exchangeName"),
        "source": "TMX",
    })


def _nasdaq_quote(symbol: str) -> dict:
    key = "us:" + symbol
    if hit := _cached(key, QUOTE_TTL):
        return hit
    for asset_class in ("stocks", "etf"):
        url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol)}/info?assetclass={asset_class}"
        try:
            data = json.loads(_get(url)).get("data")
        except Exception:
            continue
        primary = (data or {}).get("primaryData") or {}
        price = _num(primary.get("lastSalePrice"))
        if price is not None:
            return _store(key, {
                "price": price,
                "currency": "USD",
                "change": _num(primary.get("netChange")),
                "changePct": _num(primary.get("percentageChange")),
                "name": _clean_name(data.get("companyName")),
                "asOf": primary.get("lastTradeTimestamp"),
                "source": "Nasdaq",
            })
    return {"error": "Symbol not found on US exchanges"}


def _crypto_quotes(symbols: list[str]) -> dict[str, dict]:
    out, missing = {}, []
    for s in symbols:
        if hit := _cached("crypto:" + s, QUOTE_TTL):
            out[s] = hit
        else:
            missing.append(s)
    if missing:
        params = urllib.parse.urlencode({
            "symbols": ",".join(s.lower() for s in missing),
            "vs_currencies": "cad",
            "include_24hr_change": "true",
            "include_last_updated_at": "true",
        })
        try:
            data = json.loads(_get(f"https://api.coingecko.com/api/v3/simple/price?{params}"))
        except Exception as exc:
            data = {}
            for s in missing:
                out[s] = {"error": f"Crypto prices unavailable ({exc.__class__.__name__})"}
        for s in missing:
            row = data.get(s.lower())
            if row and "cad" in row:
                updated = row.get("last_updated_at")
                out[s] = _store("crypto:" + s, {
                    "price": row["cad"],
                    "currency": "CAD",
                    "changePct": row.get("cad_24h_change"),
                    "asOf": dt.datetime.fromtimestamp(updated).strftime("%b %d, %Y %H:%M") if updated else None,
                    "source": "CoinGecko",
                })
            elif s not in out:
                out[s] = {"error": "Coin not found"}
    return out


def get_quotes(symbols: list[str]) -> dict:
    """Quote ``tsx:``, ``us:`` and ``crypto:`` symbols. Every quote carries ``priceCad``."""
    keys = list(dict.fromkeys(s.strip() for s in symbols if s.strip()))[:80]
    parsed = []
    for k in keys:
        market, _, sym = k.rpartition(":")
        parsed.append((k, (market or "us").lower(), sym.upper()))

    result: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        tsx = [(k, s) for k, m, s in parsed if m == "tsx"]
        us = [(k, s) for k, m, s in parsed if m == "us"]
        for (k, _), q in zip(tsx, pool.map(_tmx_quote, [s for _, s in tsx])):
            result[k] = q
        for (k, _), q in zip(us, pool.map(_nasdaq_quote, [s for _, s in us])):
            result[k] = q
    coins = {s: k for k, m, s in parsed if m == "crypto"}
    for sym, q in _crypto_quotes(list(coins)).items():
        result[coins[sym]] = q

    fx = get_usd_cad()
    for k, q in result.items():
        if "price" not in q:
            continue
        q = dict(q)  # don't mutate the cached copy
        if q["currency"] == "CAD":
            q["priceCad"] = q["price"]
        elif "rate" in fx:
            q["priceCad"] = q["price"] * fx["rate"]
            q["fxRate"] = fx["rate"]
        result[k] = q
    return {"quotes": result, "fx": fx}


# ---------- Government of Canada yields ----------

TBILL_SERIES = {"V80691342": "1 Mo", "V80691344": "3 Mo", "V80691345": "6 Mo", "V80691346": "1 Yr"}
BOND_SERIES = {
    "BD.CDN.2YR.DQ.YLD": "2 Yr", "BD.CDN.3YR.DQ.YLD": "3 Yr", "BD.CDN.5YR.DQ.YLD": "5 Yr",
    "BD.CDN.7YR.DQ.YLD": "7 Yr", "BD.CDN.10YR.DQ.YLD": "10 Yr", "BD.CDN.LONG.DQ.YLD": "Long",
    "BD.CDN.RRB.DQ.YLD": "Real return",
}


def _latest(group: str, series: dict[str, str]) -> tuple[dict[str, float], str | None]:
    """Most recent value of each wanted series in a Valet group (series can update on different days)."""
    data = json.loads(_get(f"{VALET}/group/{group}/json?recent=5", timeout=15))
    values, date = {}, None
    for obs in sorted(data["observations"], key=lambda o: o["d"], reverse=True):
        for sid, label in series.items():
            if label not in values and (v := _num((obs.get(sid) or {}).get("v"))) is not None:
                values[label] = v
                date = date or obs["d"]
    return values, date


def get_canada_yields() -> dict:
    """Latest Government of Canada T-bill and benchmark bond yields from the Bank of Canada."""
    if hit := _cached("yields", RATES_TTL):
        return hit
    try:
        bills, bill_date = _latest("tbill_all", TBILL_SERIES)
        bonds, bond_date = _latest("bond_yields_benchmark", BOND_SERIES)
    except Exception:
        return {"error": "Bank of Canada yields unavailable"}
    return _store("yields", {
        "yields": {**bills, **bonds},
        "billDate": bill_date,
        "bondDate": bond_date,
        "source": "Bank of Canada",
    })
