# Research question: momentum-m56

- Variants tried: 3 (distinct configs). Runs: 3. Final evaluations: 0.
- Compared against: `momentum/m49_b_b2` (run 20261002-000607-0103cc7f). Adoption metric: `calmar`.

## momentum/m56_hold35_b2 (config e48e9299, run 20261002-002040-e48e9299) — PASSES the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 1.21 | 1.13 | 0.33 | 0.47 | yes |
| f1_2010_2013 | 1.88 | 1.60 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 2.20 | 2.07 | 0.96 | 1.39 | yes |
| f3_2018_2023 | 1.48 | 1.36 | 0.37 | 0.54 | yes |

## momentum/m56_hold50_b2 (config 7625b9a5, run 20261002-002049-7625b9a5) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 1.00 | 1.13 | 0.33 | 0.47 | no |
| f1_2010_2013 | 1.79 | 1.60 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 1.95 | 2.07 | 0.96 | 1.39 | no |
| f3_2018_2023 | 1.22 | 1.36 | 0.37 | 0.54 | no |

## momentum/m56_noresize_b2 (config 8964db6e, run 20261002-002058-8964db6e) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 1.12 | 1.13 | 0.33 | 0.47 | no |
| f1_2010_2013 | 1.53 | 1.60 | 0.13 | 0.15 | no |
| f2_2014_2017 | 1.92 | 2.07 | 0.96 | 1.39 | no |
| f3_2018_2023 | 1.31 | 1.36 | 0.37 | 0.54 | no |

