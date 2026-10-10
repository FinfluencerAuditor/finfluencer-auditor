# Gold Set Evaluation Report

*Benchmark evaluation of Claim Extraction, Judging Agreement, and Citation Validity.*

## Summary Metrics

| Metric | Target | Result | Status |
|---|---|---|---|
| **Gold Claims Evaluated** | - | 15 claims across 5 videos | Complete |
| **Claim Matching / Recall** | $\ge 80\%$ | **100.0%** | PASS |
| **Verdict Agreement** | $\ge 70\%$ | **100.0%** | PASS |
| **Citation Integrity (Zero Hallucination)** | 100% | **100.0%** | PASS |
| **Synthetic evidence coverage (diagnostic)** | > 0% | **90.0%** | PASS |
| **Search Calls per Checkable Claim** | $\le 3$ | **$\le 3$** (enforced in code) | PASS |

## Detailed Breakdown

| Video | Claim | Expected | Actual | Match | Citations |
|---|---|---|---|---|---|
| `fin_gold_1` | The Nifty 50 fell 10 percent during October 2... | **Supported** | **Supported** | ✅ | e1 |
| `fin_gold_1` | Reliance P/E ratio is currently trading at 25... | **Supported** | **Supported** | ✅ | e1 |
| `fin_gold_1` | This penny stock is guaranteed to give 1000% ... | **Unverifiable** | **Unverifiable** | ✅ | None |
| `fin_gold_2` | SEBI introduced stricter index derivatives ru... | **Supported** | **Supported** | ✅ | e1 |
| `fin_gold_2` | HDFC Bank dividend yield is 50 percent.... | **Contradicted** | **Contradicted** | ✅ | e1 |
| `fin_gold_2` | Every investor must buy this banking stock be... | **Unverifiable** | **Unverifiable** | ✅ | None |
| `health_gold_1` | Curcumin has demonstrated anti-inflammatory p... | **Supported** | **Supported** | ✅ | e1 |
| `health_gold_1` | Drinking turmeric milk completely cures stage... | **Contradicted** | **Contradicted** | ✅ | e1 |
| `health_gold_1` | You will never get sick if you drink this eve... | **Unverifiable** | **Unverifiable** | ✅ | None |
| `health_gold_2` | Type 2 diabetes can achieve remission through... | **Supported** | **Supported** | ✅ | e1 |
| `health_gold_2` | Eating karela juice cures type 1 diabetes ove... | **Contradicted** | **Contradicted** | ✅ | e1 |
| `health_gold_2` | Doctors hide this ancient secret from all pat... | **Unverifiable** | **Unverifiable** | ✅ | None |
| `mixed_gold_1` | RBI increased the benchmark repo rate to 6.5%... | **Supported** | **Supported** | ✅ | e1 |
| `mixed_gold_1` | My proprietary trading course guarantees 50% ... | **Unverifiable** | **Unverifiable** | ✅ | None |
| `mixed_gold_1` | Alien frequency vibrations cure kidney diseas... | **No evidence found** | **No evidence found** | ✅ | None |
