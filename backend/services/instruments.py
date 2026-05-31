from functools import lru_cache

from kiteconnect import KiteConnect


@lru_cache(maxsize=8)
def _instrument_map(api_key: str, access_token: str, exchange: str) -> dict[str, int]:
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return {
        row["tradingsymbol"]: int(row["instrument_token"])
        for row in kite.instruments(exchange)
        if row.get("instrument_token") and row.get("tradingsymbol")
    }


def resolve_instrument_token(kite: KiteConnect, tradingsymbol: str, exchange: str = "NSE") -> int | None:
    api_key = kite.api_key
    access_token = kite.access_token
    if not api_key or not access_token:
        return None

    exchanges = [exchange, "NSE", "BSE"] if exchange in {"NSE", "BSE"} else ["NSE", "BSE"]
    for candidate_exchange in dict.fromkeys(exchanges):
        token = _instrument_map(api_key, access_token, candidate_exchange).get(tradingsymbol)
        if token is not None:
            return token
    return None
