# Run `dev_gptoss_v1_verified`

Provider: `openai`  Model: `openai/gpt-oss-120b`  Retrieved chunks (k): 4

| Metric | Value |
|---|---|
| Labeled fields | 44 |
| Accuracy (exact) | 93.2% |
| Accuracy (within 0.5%) | 95.5% |
| Coverage (answered) | 95.5% |
| Ungrounded answers | 0.0% |
| Confident-wrong answers | 2.4% |
| Tokens in / out | 121,169 / 6,122 |
| Mean latency per field | 24.02s |

## Error breakdown

| Class | Count |
|---|---|
| correct | 41 |
| near_miss | 1 |
| missing | 2 |
| scale_error | 0 |
| sign_error | 0 |
| wrong_period | 0 |
| wrong_other | 0 |

## By field

| Field | n | Accuracy | Coverage | Ungrounded |
|---|---|---|---|---|
| cash | 5 | 80.0% | 100.0% | 0.0% |
| eps_diluted | 5 | 100.0% | 100.0% | 0.0% |
| long_term_debt | 4 | 100.0% | 100.0% | 0.0% |
| net_income | 4 | 100.0% | 100.0% | 0.0% |
| operating_cash_flow | 5 | 100.0% | 100.0% | 0.0% |
| operating_income | 4 | 100.0% | 100.0% | 0.0% |
| revenue | 5 | 100.0% | 100.0% | 0.0% |
| stockholders_equity | 4 | 100.0% | 100.0% | 0.0% |
| total_assets | 5 | 80.0% | 80.0% | 0.0% |
| total_liabilities | 3 | 66.7% | 66.7% | 0.0% |
