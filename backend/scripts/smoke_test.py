import sys

import httpx


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        health = client.get("/health")
        health.raise_for_status()

        status = client.get("/auth/kite/status")
        status.raise_for_status()

        signals = client.get("/signals")
        signals.raise_for_status()
        signal_rows = signals.json()

        print(f"health={health.json()}")
        print(f"kite_status={status.json()}")
        print(f"signals={len(signal_rows)}")

        if signal_rows:
            symbol = signal_rows[0]["tradingsymbol"]
            analysis = client.get(f"/portfolio/{symbol}/analysis")
            analysis.raise_for_status()
            payload = analysis.json()
            print(f"analysis_symbol={symbol} candles={len(payload.get('candles', []))}")


if __name__ == "__main__":
    main()
