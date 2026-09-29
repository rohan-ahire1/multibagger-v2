# Research question: momentum-m8

- Variants tried: 11 (distinct configs). Runs: 11. Final evaluations: 0.
- Compared against: `momentum/voladj_dev` (run 20260928-211436-f599c19f). Adoption metric: `calmar`.

## momentum/m8_top20_dev (config ffa97681, run 20260929-064523-ffa97681) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.77 | 0.62 | 0.33 | 0.48 | yes |
| f1_2010_2013 | 0.27 | 0.28 | 0.13 | 0.13 | no |
| f2_2014_2017 | 1.42 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.92 | 0.70 | 0.37 | 0.55 | yes |

## momentum/m8_noresize_dev (config a409d82d, run 20260929-064534-a409d82d) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.63 | 0.62 | 0.33 | 0.48 | yes |
| f1_2010_2013 | 0.38 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.57 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.68 | 0.70 | 0.37 | 0.55 | no |

## momentum/m8_sectorcap_dev (config 0d40c7e7, run 20260929-064546-0d40c7e7) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.62 | 0.62 | 0.33 | 0.48 | no |
| f1_2010_2013 | 0.30 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.59 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.69 | 0.70 | 0.37 | 0.55 | no |

## momentum/m8_voltarget_dev (config ba6db441, run 20260929-064554-ba6db441) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.59 | 0.62 | 0.33 | 0.48 | no |
| f1_2010_2013 | 0.28 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.60 | 1.60 | 0.96 | 1.45 | yes |
| f3_2018_2023 | 0.62 | 0.70 | 0.37 | 0.55 | no |

## momentum/m8_control_dev_d (config 99baaabb, run 20260929-065259-99baaabb) — PASSES the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.62 | 0.62 | 0.33 | 0.48 | yes |
| f1_2010_2013 | 0.28 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.60 | 1.60 | 0.96 | 1.45 | yes |
| f3_2018_2023 | 0.70 | 0.70 | 0.37 | 0.55 | yes |

## momentum/m8_top20_dev_d (config e16b6613, run 20260929-065328-e16b6613) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.77 | 0.62 | 0.33 | 0.48 | yes |
| f1_2010_2013 | 0.27 | 0.28 | 0.13 | 0.13 | no |
| f2_2014_2017 | 1.42 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.92 | 0.70 | 0.37 | 0.55 | yes |

## momentum/m8_top40_dev_d (config 1df714a6, run 20260929-065335-1df714a6) — PASSES the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.65 | 0.62 | 0.33 | 0.48 | yes |
| f1_2010_2013 | 0.31 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.70 | 1.60 | 0.96 | 1.45 | yes |
| f3_2018_2023 | 0.70 | 0.70 | 0.37 | 0.55 | yes |

## momentum/m8_noresize_dev_d (config 942a56ce, run 20260929-065343-942a56ce) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.63 | 0.62 | 0.33 | 0.48 | yes |
| f1_2010_2013 | 0.38 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.57 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.68 | 0.70 | 0.37 | 0.55 | no |

## momentum/m8_mix6_dev_d (config b2127f08, run 20260929-065351-b2127f08) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.58 | 0.62 | 0.33 | 0.48 | no |
| f1_2010_2013 | 0.31 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.47 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.63 | 0.70 | 0.37 | 0.55 | no |

## momentum/m8_sectorcap_dev_d (config 9427ce81, run 20260929-065359-9427ce81) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.62 | 0.62 | 0.33 | 0.48 | no |
| f1_2010_2013 | 0.30 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.59 | 1.60 | 0.96 | 1.45 | no |
| f3_2018_2023 | 0.69 | 0.70 | 0.37 | 0.55 | no |

## momentum/m8_voltarget_dev_d (config cff7e8c9, run 20260929-065406-cff7e8c9) — fails the bar

| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |
|---|---|---|---|---|---|
| period | 0.59 | 0.62 | 0.33 | 0.48 | no |
| f1_2010_2013 | 0.28 | 0.28 | 0.13 | 0.13 | yes |
| f2_2014_2017 | 1.60 | 1.60 | 0.96 | 1.45 | yes |
| f3_2018_2023 | 0.62 | 0.70 | 0.37 | 0.55 | no |

