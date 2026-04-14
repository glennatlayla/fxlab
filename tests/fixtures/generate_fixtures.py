#!/usr/bin/env python3
"""Generate deterministic test fixture CSV files.

Run once to create / refresh the fixture data:
    python tests/fixtures/generate_fixtures.py
"""

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

SYMBOLS = ["AAPL", "MSFT", "GOOG"]
BASE_DATE = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
BARS_PER_SYMBOL = 20
TIMEFRAME = "1m"

HEADERS = [
    "canonical_symbol",
    "source_symbol",
    "venue",
    "asset_class",
    "timeframe",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def make_bar(symbol: str, ts: datetime, base_price: float = 100.0) -> dict:
    o = round(base_price + random.uniform(-0.5, 0.5), 2)
    h = round(o + random.uniform(0.01, 1.0), 2)
    low = round(o - random.uniform(0.01, 1.0), 2)
    c = round(random.uniform(low, h), 2)
    v = random.randint(100, 10_000)
    return {
        "canonical_symbol": symbol,
        "source_symbol": symbol,
        "venue": "NASDAQ",
        "asset_class": "equity",
        "timeframe": TIMEFRAME,
        "ts": ts.isoformat(),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": v,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(rows)
    print(f"  Written: {path.name} ({len(rows)} rows)")


def generate_clean() -> list[dict]:
    rows = []
    for sym in SYMBOLS:
        price = 100.0 + SYMBOLS.index(sym) * 50
        for i in range(BARS_PER_SYMBOL):
            rows.append(make_bar(sym, BASE_DATE + timedelta(minutes=i), price))
    return rows


def generate_gapped(clean: list[dict]) -> list[dict]:
    """Remove bars 5 and 10 per symbol to create intentional gaps."""
    return [r for i, r in enumerate(clean) if i % BARS_PER_SYMBOL not in (5, 10)]


def generate_malformed(clean: list[dict]) -> list[dict]:
    rows = [r.copy() for r in clean]
    # Row 0: high < low
    rows[0]["high"] = rows[0]["low"] - 0.5
    # Row 1: negative volume
    rows[1]["volume"] = -999
    # Row 2: null timestamp
    rows[2]["ts"] = ""
    return rows


def generate_parity_left(clean: list[dict]) -> list[dict]:
    return clean.copy()


def generate_parity_mismatch(left: list[dict]) -> list[dict]:
    rows = [r.copy() for r in left]
    # Rows 3, 7, 12: close price differs by > tolerance
    for idx in (3, 7, 12):
        if idx < len(rows):
            rows[idx]["close"] = round(rows[idx]["close"] * 1.05, 2)
    return rows


if __name__ == "__main__":
    print("Generating fixtures...")
    clean = generate_clean()
    write_csv(FIXTURES_DIR / "clean_ohlcv.csv", clean)
    write_csv(FIXTURES_DIR / "gapped_ohlcv.csv", generate_gapped(clean))
    write_csv(FIXTURES_DIR / "malformed_ohlcv.csv", generate_malformed(clean))
    left = generate_parity_left(clean)
    write_csv(FIXTURES_DIR / "parity_left.csv", left)
    write_csv(FIXTURES_DIR / "parity_right_mismatch.csv", generate_parity_mismatch(left))
    write_csv(FIXTURES_DIR / "parity_right_clean.csv", left)
    print("Done.")
