# Test Fixtures

These CSV/Parquet files are used by the acceptance test suite.
Each file is deterministic and version-controlled.

| File | Purpose |
|------|---------|
| `clean_ohlcv.csv`           | Normal OHLCV bars for happy-path ingest |
| `gapped_ohlcv.csv`          | Intentional time gaps for gap detection |
| `malformed_ohlcv.csv`       | high < low, negative volume, null timestamps |
| `parity_left.csv`           | First feed for parity comparison |
| `parity_right_mismatch.csv` | Second feed with controlled price/volume deltas |
| `parity_right_clean.csv`    | Second feed identical to left (clean parity) |

Fixture generation script: `tests/fixtures/generate_fixtures.py`
