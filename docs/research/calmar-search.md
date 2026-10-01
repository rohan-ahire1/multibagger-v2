# Search for a higher Calmar (running summary, from 2026-10-01)

The user asked for Calmar near 1 or more, using published research. Reference: pin `momentum/m19_gold20_invvol_b2`,
22.80% CAGR, 32.05% max DD (March 2020), Calmar 0.712, folds 0.483 / 1.643 / 0.826. Every idea is pre-registered in
its own `mNN.md`; this file only summarises.

| M | Idea (source) | Best whole-period Calmar | Robust? | Verdict |
|---|---|---|---|---|
| 27 | Monthly rotation book ↔ gold by 1/3/6/12-month returns (Faber, Antonacci, Keller) | 0.960 (offset 0) | no: 2 of 4 offsets win, mean 0.713 | fails f2 |
| 28 | Same rotation in four timing tranches (Hoffstein et al. 2020) | 0.914 (22% DD, 20.3% CAGR) | bootstrap beats gold20 tranches only 48% | crash insurance, not adopted |
| 29 | Low-volatility sleeve, 50/50 with the pin (Blitz & van Vliet 2007) | 0.713 | same as pin | fails f3 |
| 30 | Rank by high-to-price, the crash-free part of momentum (Büsing, Mohrschladt & Siedhoff 2024) | 0.712 (HTP/vol) | HTP alone 0.448, 42% DD | fails f2 |
| 31 | Data: 18 missing demergers/splits/rights, 3 manual fixes that never applied | pin unchanged | | new dataset `nse_research@2026-10-01` |
| 32 | Conditional volatility targeting: shrink the picks only after a top-quintile-volatility month (Bongaerts, Kang & van Dijk 2020) | 0.687 | DD unchanged (Feb 2020 was calm) | fails period, f3 |
| 33 | Lower liquidity floor ₹5 → ₹2 / ₹1 crore a day (Lee & Swaminathan 2000; Indian momentum-liquidity studies) | 0.865 (₹2 cr, 26.8% CAGR, 31.0% DD) / 0.881 (₹1 cr) | yes: 4/4 offsets, 25 bps, bootstrap 95%, capacity ₹2.2 cr | **adopted (₹2 cr), new pin** |
| 34 | The ₹2 crore floor on the other three books (robustness) | +0.17–0.20 on every book; invvol_b1 0.893 | invvol_b1 vs pin: bootstrap 61% | floor generalizes; pin unchanged |
| 35 | Untouched 2007–09 window for the ₹2 crore pin; found ETFs leaking into pre-2011 runs (fixed) | pin 0.109 vs ₹5 cr 0.150; both ~65% DD in 2008 | floor not confirmed out of sample | M26's 48% DD was wrong (LIQUIDBEES); rotation 0.824 / 41% DD |
| 36 | M28 gold-rotation tranches on the ₹2 crore book | rot 0.883, half 0.951 (25.7% DD) vs pin 0.865 | fails f1, f2; bootstrap 45% | crash insurance for ~2.4 pts CAGR; month-end decision beats offsets in 97% of resamples |
| 37 | Does the month-end decision day win out of sample (2007–09)? | offset 0 lowest CAGR (7.1% vs 12–15%) | no | pin's edge over other days is partly luck; expect ~0.80 |
| 38 | ₹2 vs ₹5 crore floor on 2007–09 at four decision days | mean CAGR 11.85% vs 11.72% | 2 of 4 each | floor neutral early; M35's loss was the decision day |
| 39 | Circuit-locked fills, BE-series and delisted exits in the simulator | locked fills < 1%; ≤ 0.15 pt CAGR a year | | no change needed |
| 40 | Drop winners with the lowest delivery share (NSE delivery files; Lee & Swaminathan 2000 on speculative volume) | 0.913 (drop 40%; 28.65% CAGR, 31.4% DD; folds 1.10/1.98/1.01) | yes: 4/4 offsets, 25 bps, bootstrap 87%, early window better | **adopted, new pin** |
| 41 | Optuna pilot: walk-forward search of 7 settings (60 trials per step) | test f2 1.738 vs pin 1.736; f3 1.212 vs 1.037 | pilot only | pushes to more gold, stronger delivery filter, ₹1 cr floor; ranges too narrow |
| 42 | Optuna full: 300 trials per step, 3 walk-forward steps, wider ranges, 25 bps check | test: A 1.51 vs pin 1.74; B 1.31 vs 1.04; C 2.50 vs 1.88 | B, C pass at 25 bps; A fails | bar fails (step A); all steps pick delivery drop 0.8, fewer names, more gold |
| 43 | Paper book with the delivery filter (daily delivery files); trading-gap audit | pin unchanged | live decisions equal backtest Feb–Jul 2026 | draft book ready, not deployed |
| 44 | No picks across a trading gap over 30 days (data correctness) | 0.912 vs 0.913; four-offset mean 0.898 both | neutral | not adopted; recommended for live as a safety rule |
| 45 | Rank on months 12 to 7 instead of 12 to 2 (Novy-Marx 2012) | 0.70 (21.7% CAGR, 31.0% DD) | | fails every window; recent months carry the signal |
| 46 | Rebalance every 3 months instead of monthly (Jegadeesh & Titman 1993; Novy-Marx & Velikov 2016); data fixes ORIENTPPR 2013, GEOINFO 2007 (`nse_research@2026-10-02`, pin unchanged) | 0.887 (25.6% CAGR, 28.9% DD) | 7-run mean 0.873 vs 0.898 | fails f1, f2; monthly refresh earns more than its costs |

What the evidence says so far:

- The max drawdown of every long-only book is March 2020, a one-month crash a monthly rule cannot react to. Calmar is
  roughly CAGR / (that loss). Gold is the only asset with history from 2007 that did not fall with Indian stocks;
  gilt ETFs start in 2016, MON100 trades at a 10–30% premium to NAV.
- Ways that cut the 2020 loss (rotation, low-vol) cost about the same share of return in strong years.
- Timing luck alone moves Calmar by ±0.2 between month-end and a few days earlier.
