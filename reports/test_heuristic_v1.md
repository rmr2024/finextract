# Run `test_heuristic_v1`

Provider: `heuristic`  Model: `None`  Retrieved chunks (k): 6

| Metric | Value |
|---|---|
| Labeled fields | 137 |
| Accuracy (exact) | 46.0% |
| Accuracy (within 0.5%) | 46.0% |
| Coverage (answered) | 75.9% |
| Ungrounded answers | 0.0% |
| Confident-wrong answers | 39.4% |
| Tokens in / out | 0 / 0 |
| Mean latency per field | 0.00s |

## Error breakdown

| Class | Count |
|---|---|
| correct | 63 |
| near_miss | 0 |
| missing | 33 |
| scale_error | 14 |
| sign_error | 2 |
| wrong_period | 1 |
| wrong_other | 24 |

## By field

| Field | n | Accuracy | Coverage | Ungrounded |
|---|---|---|---|---|
| cash | 14 | 50.0% | 85.7% | 0.0% |
| eps_diluted | 15 | 53.3% | 80.0% | 0.0% |
| long_term_debt | 14 | 42.9% | 85.7% | 0.0% |
| net_income | 15 | 46.7% | 86.7% | 0.0% |
| operating_cash_flow | 15 | 20.0% | 60.0% | 0.0% |
| operating_income | 12 | 66.7% | 75.0% | 0.0% |
| revenue | 15 | 33.3% | 80.0% | 0.0% |
| stockholders_equity | 13 | 15.4% | 46.2% | 0.0% |
| total_assets | 15 | 66.7% | 73.3% | 0.0% |
| total_liabilities | 9 | 77.8% | 88.9% | 0.0% |
