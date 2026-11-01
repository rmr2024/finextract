# Run `test5_gptoss_v1_verified`

Provider: `openai`  Model: `openai/gpt-oss-120b`  Retrieved chunks (k): 4

| Metric | Value |
|---|---|
| Labeled fields | 44 |
| Accuracy (exact) | 84.1% |
| Accuracy (within 0.5%) | 84.1% |
| Coverage (answered) | 95.5% |
| Ungrounded answers | 0.0% |
| Confident-wrong answers | 11.9% |
| Tokens in / out | 114,927 / 5,199 |
| Mean latency per field | 26.01s |

## Error breakdown

| Class | Count |
|---|---|
| correct | 37 |
| near_miss | 0 |
| missing | 2 |
| scale_error | 0 |
| sign_error | 0 |
| wrong_period | 1 |
| wrong_other | 4 |

## By field

| Field | n | Accuracy | Coverage | Ungrounded |
|---|---|---|---|---|
| cash | 5 | 100.0% | 100.0% | 0.0% |
| eps_diluted | 5 | 80.0% | 100.0% | 0.0% |
| long_term_debt | 4 | 75.0% | 100.0% | 0.0% |
| net_income | 5 | 80.0% | 100.0% | 0.0% |
| operating_cash_flow | 5 | 80.0% | 80.0% | 0.0% |
| operating_income | 4 | 100.0% | 100.0% | 0.0% |
| revenue | 5 | 100.0% | 100.0% | 0.0% |
| stockholders_equity | 4 | 50.0% | 100.0% | 0.0% |
| total_assets | 5 | 80.0% | 80.0% | 0.0% |
| total_liabilities | 2 | 100.0% | 100.0% | 0.0% |
