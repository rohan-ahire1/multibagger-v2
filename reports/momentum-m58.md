# Research question: momentum-m58

- Variants tried: 1 (distinct configs). Runs: 1. Final evaluations: 0.
- Compared against: `momentum/m49_b_b2` (run 20261002-000607-0103cc7f). Adoption metric: `calmar`.

## momentum/m58_top20_b2 (config d82665ba, run 20261002-002504-d82665ba) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 1.19 | 1.13 | 0.33 | 0.47 | yes |
| f1_2010_2013 | 1.60 | 1.60 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 1.94 | 2.07 | 0.96 | 1.39 | no |
| f3_2018_2023 | 1.53 | 1.36 | 0.37 | 0.54 | yes |

