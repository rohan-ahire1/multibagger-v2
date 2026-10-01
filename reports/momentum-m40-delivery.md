# Research question: momentum-m40-delivery

- Variants tried: 3 (distinct configs). Runs: 3. Final evaluations: 0.
- Compared against: `momentum/m33_adv2cr_gold20_b2` (run 20261001-135135-a38245bf). Adoption metric: `calmar`.

## momentum/m40_base_gold20_b2 (config 2de733c2, run 20261001-161737-2de733c2) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.87 | 0.87 | 0.33 | 0.47 | no |
| f1_2010_2013 | 0.66 | 0.66 | 0.13 | 0.15 | no |
| f2_2014_2017 | 1.79 | 1.79 | 0.96 | 1.39 | no |
| f3_2018_2023 | 0.94 | 0.94 | 0.37 | 0.54 | no |

## momentum/m40_deliv20_gold20_b2 (config c29fc356, run 20261001-161746-c29fc356) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.86 | 0.87 | 0.33 | 0.47 | no |
| f1_2010_2013 | 0.83 | 0.66 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 1.83 | 1.79 | 0.96 | 1.39 | yes |
| f3_2018_2023 | 0.98 | 0.94 | 0.37 | 0.54 | yes |

## momentum/m40_deliv40_gold20_b2 (config 9fc4ae73, run 20261001-161755-9fc4ae73) — PASSES the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.91 | 0.87 | 0.33 | 0.47 | yes |
| f1_2010_2013 | 1.10 | 0.66 | 0.13 | 0.15 | yes |
| f2_2014_2017 | 1.98 | 1.79 | 0.96 | 1.39 | yes |
| f3_2018_2023 | 1.01 | 0.94 | 0.37 | 0.54 | yes |

