import csv
import io
import logging
import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_holdings(url: str, target_date: date) -> Optional[dict]:
    """Fetch ETF holdings for a specific date. Returns None if no data available."""
    if url.startswith("roundhill://"):
        return _fetch_roundhill(url.removeprefix("roundhill://"), target_date)
    if url.startswith("wisdomtree://"):
        return _fetch_wisdomtree(url.removeprefix("wisdomtree://"))
    if url.startswith("yfinance://"):
        return _fetch_yfinance_holdings(url.removeprefix("yfinance://"))
    if "ishares.com" in url:
        return _fetch_ishares(url, target_date)
    return _fetch_timeetf(url, target_date)


# ─── timeetf.co.kr ────────────────────────────────────────────────────────────

def _fetch_timeetf(url: str, target_date: date) -> Optional[dict]:
    base_url = url.split("?")[0]
    params = {"pdfDate": target_date.strftime("%Y-%m-%d")}

    idx_match = re.search(r"idx=(\d+)", url)
    if idx_match:
        params["idx"] = idx_match.group(1)

    resp = requests.get(base_url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    aum_100m = _parse_timeetf_aum(soup)
    holdings = _parse_timeetf_holdings(soup)

    if not holdings:
        return None

    return {"aum_100m": aum_100m, "holdings": holdings}


def _parse_timeetf_aum(soup: BeautifulSoup) -> Optional[float]:
    for dt in soup.find_all("dt"):
        if "순자산총액" in dt.get_text():
            dd = dt.find_next_sibling("dd")
            if dd:
                raw = dd.get_text(strip=True).replace(",", "").replace("억원", "").strip()
                try:
                    return float(raw)
                except ValueError:
                    pass
    return None


def _parse_timeetf_holdings(soup: BeautifulSoup) -> list:
    table = soup.select_one("table.table3.moreList1 tbody")
    if not table:
        return []

    holdings = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        try:
            holdings.append(
                {
                    "ticker_code": cells[0].get_text(strip=True),
                    "stock_name": cells[1].get_text(strip=True),
                    "quantity": int(cells[2].get_text(strip=True).replace(",", "")),
                    "valuation_krw": int(cells[3].get_text(strip=True).replace(",", "")),
                    "weight_pct": float(cells[4].get_text(strip=True).replace(",", "")),
                }
            )
        except (ValueError, IndexError):
            continue

    return holdings


# ─── iShares ──────────────────────────────────────────────────────────────────

def _fetch_ishares(url: str, target_date: date) -> Optional[dict]:
    date_str = target_date.strftime("%Y%m%d")
    full_url = f"{url}&asOfDate={date_str}"

    resp = requests.get(full_url, headers={**HEADERS, "Referer": "https://www.ishares.com/"}, timeout=15)
    resp.raise_for_status()

    if "text/csv" not in resp.headers.get("Content-Type", ""):
        return None

    return _parse_ishares_csv(resp.text)


def _parse_ishares_csv(text: str) -> Optional[dict]:
    lines = text.splitlines()

    # Find column header row
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or '"Ticker"' in line[:20]:
            header_idx = i
            break

    if header_idx is None:
        return None

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))

    holdings = []
    for row in reader:
        ticker = (row.get("Ticker") or "").strip().strip('"')
        name = (row.get("Name") or "").strip().strip('"')
        asset_class = (row.get("Asset Class") or "").strip().strip('"')

        if not name or asset_class not in ("Equity", "Cash", "Money Market"):
            continue

        try:
            quantity_raw = (row.get("Quantity") or "0").strip().strip('"').replace(",", "")
            weight_raw = (row.get("Weight (%)") or "0").strip().strip('"').replace(",", "")
            mktval_raw = (row.get("Market Value") or "0").strip().strip('"').replace(",", "")

            quantity = int(float(quantity_raw)) if quantity_raw and quantity_raw != "-" else 0
            weight_pct = float(weight_raw) if weight_raw and weight_raw != "-" else 0.0
            valuation = int(float(mktval_raw)) if mktval_raw and mktval_raw != "-" else 0

            if not ticker or ticker == "-":
                ticker = f"CASH"

            holdings.append({
                "ticker_code": ticker,
                "stock_name": name,
                "quantity": quantity,
                "valuation_krw": valuation,  # USD value stored in this field
                "weight_pct": weight_pct,
            })
        except (ValueError, KeyError):
            continue

    if not holdings:
        return None

    return {"aum_100m": None, "holdings": holdings}


# ─── Roundhill Investments ───────────────────────────────────────────────────

_ROUNDHILL_BASE = "https://www.roundhillinvestments.com/assets/data/FilepointRoundhill.40RU.RU_Holdings_{}.csv"
_ROUNDHILL_MAX_LOOKBACK = 15


def _fetch_roundhill(fund_code: str, target_date: date) -> Optional[dict]:
    for offset in range(_ROUNDHILL_MAX_LOOKBACK):
        d = target_date - __import__("datetime").timedelta(days=offset)
        date_str = d.strftime("%m%d%Y")
        url = _ROUNDHILL_BASE.format(date_str)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False)
            if resp.status_code != 200:
                continue
        except requests.RequestException:
            continue

        holdings = _parse_roundhill_csv(resp.text, fund_code)
        if holdings:
            return {"aum_100m": None, "holdings": holdings}

    return None


def _parse_roundhill_csv(text: str, fund_code: str) -> list:
    reader = csv.DictReader(io.StringIO(text))
    holdings = []
    for row in reader:
        if row.get("Account") != fund_code:
            continue
        if row.get("MoneyMarketFlag") == "Y":
            continue
        ticker = (row.get("StockTicker") or "").strip()
        name = (row.get("SecurityName") or "").strip()
        if not name or ticker in ("Cash&Other",) or ticker.startswith("CASH"):
            continue
        try:
            weight_str = (row.get("Weightings") or "0").strip().rstrip("%")
            weight_pct = float(weight_str)
            shares = int(float((row.get("Shares") or "0").strip()))
            mkt_val = int(float((row.get("MarketValue") or "0").strip()))
            holdings.append({
                "ticker_code": ticker,
                "stock_name": name,
                "quantity": shares,
                "valuation_krw": mkt_val,
                "weight_pct": weight_pct,
            })
        except (ValueError, KeyError):
            continue
    return holdings


# ─── WisdomTree (Playwright, non-headless to bypass Cloudflare) ──────────────

def _fetch_wisdomtree(fund_code: str) -> Optional[dict]:
    import json, re

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed, falling back to yfinance for %s", fund_code)
        return _fetch_yfinance_holdings(fund_code)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled'],
            )
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/148.0.0.0 Safari/537.36'
                ),
            )
            page = context.new_page()
            page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )
            page.goto(
                f'https://www.wisdomtree.com/us/products/megatrends/{fund_code.lower()}#holdings',
                wait_until='domcontentloaded',
                timeout=30000,
            )
            page.wait_for_timeout(8000)
            html = page.content()
            browser.close()
    except Exception:
        logger.exception("Playwright fetch failed for WisdomTree %s", fund_code)
        return _fetch_yfinance_holdings(fund_code)

    return _parse_wisdomtree_html(html, fund_code)


def _parse_wisdomtree_html(html: str, fund_code: str) -> Optional[dict]:
    import json, re

    idx = html.find('\\"ranking\\":[{\\"_key\\"')
    escaped = True
    if idx < 0:
        idx = html.find('"ranking":[{"_key"')
        escaped = False
    if idx < 0:
        logger.warning("WisdomTree %s: holdings JSON not found in page", fund_code)
        return None

    chunk = html[idx:idx + 100000]
    arr_start = chunk.index('[')
    bracket_count = 0
    for i, c in enumerate(chunk[arr_start:], arr_start):
        if c == '[':
            bracket_count += 1
        elif c == ']':
            bracket_count -= 1
        if bracket_count == 0:
            arr_str = chunk[arr_start:i + 1]
            if escaped:
                arr_str = arr_str.replace('\\"', '"').replace('\\\\', '\\')
            break
    else:
        return None

    try:
        data = json.loads(arr_str)
    except json.JSONDecodeError:
        logger.exception("WisdomTree %s: JSON parse failed", fund_code)
        return None

    holdings = []
    for h in data:
        if h.get('classTicker') != fund_code.upper():
            continue
        name = h.get('constituentName', '').strip()
        if not name:
            continue
        weight = round(h.get('pctWeight', 0) * 100, 2)
        sedol = h.get('descriptorB', '')
        holdings.append({
            'ticker_code': sedol or name[:12],
            'stock_name': name,
            'quantity': 1,
            'valuation_krw': 0,
            'weight_pct': weight,
        })

    if not holdings:
        return None

    logger.info("WisdomTree %s: fetched %d holdings", fund_code, len(holdings))
    return {'aum_100m': None, 'holdings': holdings}


# ─── yfinance (fallback) ────────────────────────────────────────────────────

def _fetch_yfinance_holdings(ticker: str) -> Optional[dict]:
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        top = t.funds_data.top_holdings
    except Exception:
        logger.exception("yfinance holdings fetch failed for %s", ticker)
        return None

    if top is None or top.empty:
        return None

    holdings = []
    for symbol, row in top.iterrows():
        name = row.get("Name", symbol)
        weight = row.get("Holding Percent", 0.0) * 100
        holdings.append({
            "ticker_code": symbol,
            "stock_name": name,
            "quantity": 1,
            "valuation_krw": 0,
            "weight_pct": round(weight, 2),
        })

    return {"aum_100m": None, "holdings": holdings}


def fetch_etf_returns(yf_ticker: str, period: str = "5d") -> list[dict]:
    """Fetch daily close prices and returns via yfinance."""
    import yfinance as yf

    try:
        t = yf.Ticker(yf_ticker)
        hist = t.history(period=period)
    except Exception:
        logger.exception("yfinance returns fetch failed for %s", yf_ticker)
        return []

    if hist.empty:
        return []

    results = []
    closes = hist["Close"]
    for i, (dt, close) in enumerate(closes.items()):
        d = dt.date() if hasattr(dt, "date") else dt
        daily_ret = ((close / closes.iloc[i - 1]) - 1) * 100 if i > 0 else None
        results.append({
            "date": str(d),
            "close_price": round(float(close), 4),
            "daily_return_pct": round(float(daily_ret), 4) if daily_ret is not None else None,
        })

    return results
