import html
import re

import httpx


RATIO_NAMES = {
    "Market Cap": "market_cap",
    "Stock P/E": "pe",
    "Book Value": "book_value",
    "ROCE": "roce",
    "ROE": "roe",
    "Debt to equity": "debt_to_equity",
    "Dividend Yield": "dividend_yield",
}


def fetch_screener_snapshot(tradingsymbol: str) -> dict[str, str]:
    url = f"https://www.screener.in/company/{tradingsymbol}/consolidated/"
    try:
        response = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
        response.raise_for_status()
    except Exception:
        return {}

    snapshot: dict[str, str] = {}
    for item in re.findall(r'<li class="flex flex-space-between".*?</li>', response.text, flags=re.DOTALL):
        name_match = re.search(r'<span class="name">\s*(.*?)\s*</span>', item, flags=re.DOTALL)
        value_match = re.search(r'<span class="nowrap value">\s*(.*?)\s*</span>', item, flags=re.DOTALL)
        if not name_match or not value_match:
            continue
        name = re.sub(r"<.*?>", "", name_match.group(1)).strip()
        key = RATIO_NAMES.get(html.unescape(name))
        if key is None:
            continue
        value = re.sub(r"<.*?>", "", value_match.group(1))
        cleaned_value = " ".join(html.unescape(value).split())
        if not cleaned_value or cleaned_value in {"₹", "%", "Cr.", "₹ Cr."}:
            continue
        snapshot[key] = cleaned_value
    return snapshot
