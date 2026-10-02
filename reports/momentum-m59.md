# Research question: momentum-m59

- Variants tried: 2 (distinct configs). Runs: 2. Final evaluations: 0.
- Compared against: `momentum/m49_b_b2` (run 20261002-000607-0103cc7f). Adoption metric: `calmar`.

## momentum/m59_rot_b2 (config 1b7d48cf, run 20261002-002657-1b7d48cf) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 1.24 | 1.13 | 0.33 | 0.47 | yes |
| f1_2010_2013 | 1.64 | 1.60 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 1.55 | 2.07 | 0.96 | 1.39 | no |
| f3_2018_2023 | 1.48 | 1.36 | 0.37 | 0.54 | yes |

## blend/m59_half_b2 (config 65b54049, run 20261002-002838-65b54049) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 1.28 | 1.13 | 0.33 | 0.47 | yes |
| f1_2010_2013 | 1.79 | 1.60 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 1.83 | 2.07 | 0.96 | 1.39 | no |
| f3_2018_2023 | 1.54 | 1.36 | 0.37 | 0.54 | yes |

