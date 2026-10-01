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

What the evidence says so far:

- The max drawdown of every long-only book is March 2020, a one-month crash a monthly rule cannot react to. Calmar is
  roughly CAGR / (that loss). Gold is the only asset with history from 2007 that did not fall with Indian stocks;
  gilt ETFs start in 2016, MON100 trades at a 10–30% premium to NAV.
- Ways that cut the 2020 loss (rotation, low-vol) cost about the same share of return in strong years.
- Timing luck alone moves Calmar by ±0.2 between month-end and a few days earlier.
