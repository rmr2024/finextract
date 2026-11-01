# Run `test5_gptoss_v1`

Provider: `openai`  Model: `openai/gpt-oss-120b`  Retrieved chunks (k): 4

| Metric | Value |
|---|---|
| Labeled fields | 44 |
| Accuracy (exact) | 75.0% |
| Accuracy (within 0.5%) | 75.0% |
| Coverage (answered) | 95.5% |
| Ungrounded answers | 14.3% |
| Confident-wrong answers | 21.4% |
| Tokens in / out | 114,927 / 5,199 |
| Mean latency per field | 26.01s |

## Error breakdown

| Class | Count |
|---|---|
| correct | 33 |
| near_miss | 0 |
| missing | 2 |
| scale_error | 0 |
| sign_error | 0 |
| wrong_period | 0 |
| wrong_other | 9 |

## By field

| Field | n | Accuracy | Coverage | Ungrounded |
|---|---|---|---|---|
| cash | 5 | 80.0% | 100.0% | 20.0% |
| eps_diluted | 5 | 80.0% | 100.0% | 20.0% |
| long_term_debt | 4 | 75.0% | 100.0% | 0.0% |
| net_income | 5 | 60.0% | 100.0% | 20.0% |
| operating_cash_flow | 5 | 60.0% | 80.0% | 25.0% |
| operating_income | 4 | 100.0% | 100.0% | 0.0% |
| revenue | 5 | 100.0% | 100.0% | 0.0% |
| stockholders_equity | 4 | 25.0% | 100.0% | 50.0% |
| total_assets | 5 | 80.0% | 80.0% | 0.0% |
| total_liabilities | 2 | 100.0% | 100.0% | 0.0% |
