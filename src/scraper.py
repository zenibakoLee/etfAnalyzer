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
    base_url = url.split("?")[0]
    params = {"pdfDate": target_date.strftime("%Y-%m-%d")}

    idx_match = re.search(r"idx=(\d+)", url)
    if idx_match:
        params["idx"] = idx_match.group(1)

    resp = requests.get(base_url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    aum_100m = _parse_aum(soup)
    holdings = _parse_holdings(soup)

    if not holdings:
        return None

    return {"aum_100m": aum_100m, "holdings": holdings}


def _parse_aum(soup: BeautifulSoup) -> Optional[float]:
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


def _parse_holdings(soup: BeautifulSoup) -> list:
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
