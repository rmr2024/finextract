# Run `dev_gptoss_v1`

Provider: `openai`  Model: `openai/gpt-oss-120b`  Retrieved chunks (k): 4

| Metric | Value |
|---|---|
| Labeled fields | 44 |
| Accuracy | 88.6% |
| Coverage (answered) | 95.5% |
| Ungrounded answers | 14.3% |
| Confident-wrong answers | 7.1% |
| Tokens in / out | 121,169 / 6,122 |
| Mean latency per field | 24.02s |

## Error breakdown

| Class | Count |
|---|---|
| correct | 39 |
| missing | 2 |
| scale_error | 0 |
| sign_error | 0 |
| wrong_period | 0 |
| wrong_other | 3 |

## By field

| Field | n | Accuracy | Coverage | Ungrounded |
|---|---|---|---|---|
| cash | 5 | 100.0% | 100.0% | 20.0% |
| eps_diluted | 5 | 80.0% | 100.0% | 20.0% |
| long_term_debt | 4 | 100.0% | 100.0% | 25.0% |
| net_income | 4 | 100.0% | 100.0% | 0.0% |
| operating_cash_flow | 5 | 100.0% | 100.0% | 0.0% |
| operating_income | 4 | 100.0% | 100.0% | 0.0% |
| revenue | 5 | 80.0% | 100.0% | 20.0% |
| stockholders_equity | 4 | 100.0% | 100.0% | 25.0% |
| total_assets | 5 | 80.0% | 80.0% | 0.0% |
| total_liabilities | 3 | 33.3% | 66.7% | 50.0% |
