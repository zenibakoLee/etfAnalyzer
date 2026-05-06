import csv
import io
import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_holdings(url: str, target_date: date) -> Optional[dict]:
    """Fetch ETF holdings for a specific date. Returns None if no data available."""
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
