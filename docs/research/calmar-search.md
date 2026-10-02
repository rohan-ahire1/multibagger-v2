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
| 47 | Stronger delivery filter alone: drop 60% / 80% (M42's consistent pick) | 0.931 (60%; 28.0% CAGR, 30.1% DD) / 0.919 (80%; 25.5%, 27.7%) | not run (fails a) | both fail f2 by 0.04; better f1, f3 |
| 48 | M42's three tuned settings on 2007–09, the window no search saw | C 0.527 mean (19.3% CAGR, 36.6% DD) vs pin 0.219 (12.7%, 58.1%) | A, C 4/4 offsets; B 3/4 | tuned settings hold up out of sample, mostly via less 2008 loss |
| 49 | M42's tuned settings as ordinary candidates (full bar, offsets, 25 bps, capacity) | **B 1.125 (29.3% CAGR, 26.1% DD; folds 1.60 / 2.07 / 1.36)**; C 1.264 and A 1.075 fail f2 | B: 4/4 offsets (mean 1.106 vs 0.898), 25 bps, capacity 0.78% | **adopted: new pin `momentum/m49_b_b2`** (tuned on 2010–17; disclosed) |
| 50 | One-step neighbours of the new pin (12 configs, information only) | median 1.111, min 1.040 (ADV ₹2 cr), max 1.193 (top 20) | all 12 above the old pin's 0.913 | plateau, not a knife-edge |
| 51 | New pin plus the M44 gap rule; paper draft end to end | 1.120 vs 1.125 | live decisions equal research Jan–Sep 2026 | draft `momentum_b_top25_gold25_deliv80_gap` ready, not deployed |
| 52 | Stitched M42 walk-forward 2014–23 (each period uses only earlier tuning) | 0.953 (24.8% CAGR, 26.1% DD) vs old pin 1.049, new pin 1.262 (both partly in-sample) | out of sample by construction | realistic expectation ≈ 0.95–1.1 |
| 53 | Drop names with the weakest recent delivered volume vs their past year (Gervais, Kaniel & Mingelgrin 2001) | 1.081 (drop 25%) / 0.983 (50%) vs pin 1.125 | | fails every window; churns the book |
| 54 | The pin in four tranches (offsets 0/5/10/15; Hoffstein et al. 2020) | 1.105 vs 1.125 | 26.65% | fails; same drawdowns, so ~1.10 is the timing-luck-free pin |
| 55 | Rank on daytime-only or overnight-only return (Lou, Polk & Skouras 2019; Barardehi, Bogousslavsky & Muravyev) | 0.736 (daytime) / 0.599 (overnight) vs 1.125 | | fails; the whole return is the signal |
| 56 | Hold buffer / no resizing on the new pin (Novy-Marx & Velikov 2016) | hold 35: 1.214 at month-end (30.9% CAGR, 25.4% DD) | loses offsets 5/10/15; four-offset mean 1.089 vs 1.106 | fails; month-end gain is timing luck, but wins at 25 bps |
| 57 | Decide every 5 / 10 sessions with a hold buffer (Novy-Marx & Velikov 2016; Hoffstein et al. 2020) | 1.115 (e5, hold 35) / 1.104 / 1.071 vs 1.125 | | fails; drawdowns not lower |
| 58 | Top 20 instead of 25 as a full candidate (M42 picked 20 in steps A, C) | 1.193 (31.6% CAGR, 26.5% DD) | wins 4/4 offsets, 25 bps, 2007–09 4/4 | **fails f2 only (1.94 vs 2.07); near-miss for the user** |
| 59 | Book-or-gold rotation on the new pin, alone and 50/50 with the pin (M27/M36 rules) | half 1.279 (30.0% CAGR, 23.5% DD); rotation 1.235 | half: 3/4 offsets (mean 1.141 vs 1.106), 25 bps 1.196, 2007–09 mean 0.62 vs 0.28 | **fails f2 only; half is a near-miss with real 2008 protection** |
| 60 | Delivery drop past the search edge: 0.85 / 0.90 | 1.024 (0.85) vs 1.125 | | fails; 0.8 is the peak (0.90 blocked by a verified GTL crash, not re-run) |
| 61 | Top 20 inside the half-rotation blend (M58 + M59) | **1.313 (32.4% CAGR, 24.7% DD)** | 3/4 offsets (mean 1.157), 25 bps 1.229, 2007–09 mean 0.635 vs 0.284 | **fails f2 only (1.72 vs 2.07); best combined near-miss** |
| 62 | M61 book in four decision-day tranches (information) | 1.201 (30.4% CAGR, 25.3% DD) vs pin tranches 1.105 | 2007–09: 0.630 (40% DD) vs 0.284 (51% DD) | information; the honest form of the near-miss |
| 63 | Slower rotation signal (3/6/12 m) in the M61 book | 1.267 | offsets 0.968 / 1.155 / 1.175; 2007–09 0.623 | fails f2 (1.82); no gain over M61 |
| 64 | Top 15, past M42's search edge | 1.161 (32.2% CAGR, 27.7% DD) | four-offset mean 1.167; 25 bps 1.111; 2007–09 0.357 | fails f2 (1.75); concentration peaks at 15–20 |
| 65 | Square-root market impact at ₹10 lakh – ₹10 crore (information) | pin 1.098 / 1.065 / 1.006 / 0.863 | M61 1.271 / 1.220 / 1.133 / 0.940 | information; edge holds to ~₹2 crore, ordering unchanged |
| 66 | ADV floor ₹50 lakh, past M42's search edge (Amihud 2002) | 1.164 (30.4% CAGR, 26.1% DD) | f2 2.09 beats the pin; 2007–09 0.288 | fails f1 (1.52 vs 1.60) |
| 67 | Lookback ensemble 189 / 273 / 378, a third each (specification diversification) | 1.076 (27.9% CAGR, 26.0% DD) | four-offset mean 1.078; 2007–09 0.281 | fails everywhere |
| 68 | Near-misses in four decision-day tranches (information) | **half (M59) 1.176: folds 1.69 / 2.15 / 1.38, all above the pinned run**; M61 1.201; top 20 1.145 | 2007–09 half 0.617, M61 0.630 vs 0.284 | information; half beats the pinned run everywhere but trails the pin's own tranches in f2 (2.149 vs 2.199) |
| 69 | Tranche books at 25 bps (information) | pin 1.059, half 1.100, M61 1.121 | half vs the pin's 25 bps run: f2 1.962 vs 1.971, f3 1.295 vs 1.310 | information; half tranches fail the 25 bps check by a hair |
| 70 | Half-rotation rule on the out-of-sample walk-forward 2014–23 (information) | **1.202 (28.4% CAGR, 23.6% DD) vs plain 0.953 (24.8%, 26.1%)** | 4 tranches: 1.159 vs 0.956 | information; largest out-of-sample gain so far |
| 71 | Smaller rotation share: 80/20 and 90/10 pin/rotation (grid seen before pre-registration; disclosed) | w90 1.155 (folds 1.63 / 2.08 / 1.40), w80 1.185 | w90 passes offsets, 25 bps, 2007–09 by hairs; w80 fails 25 bps f2; w90 tranche f2 2.188 vs pin tranche 2.199 | fails in tranche form; fold-2 pass at offset 0 is timing luck |
| 72 | Six published overlays re-tested on the current pin: sector cap, residual momentum, 52-week high, absolute momentum, MAX filter, 10% stop | stop10 **1.346 (27.0% CAGR, 20.1% DD)**; max10 1.115; sector5 1.122 | stop10 folds 1.32 / 1.75 / 1.70 | none pass; stop10 fails f1, f2 (followed up in M73) |
| 73 | Stop-loss 10 / 15 / 20% at all decision days, 25 bps, 2007–09; 10% stop in tranches (Han, Zhou & Zhu 2016) | stop tranches **1.513 (26.9% CAGR, 17.8% DD)** vs pin tranches 1.105 (29.5%, 26.7%) | stop10 beats the pin at 4/4 offsets, 25 bps, 2007–09 (0.41 vs 0.28); bootstrap 87% | fails f1, f2 at every level; lowers DD robustly, costs ~2.5 pts CAGR |
| 74 | 10% stop with top 20 (t20s10) or with gold 0.10 (g10s10) | g10s10 tranches **1.514 (30.5% CAGR, 20.1% DD)**; t20s10 tranches 1.472 (27.5%, 18.7%) | g10s10 vs pin tranches: Calmar higher 82%, CAGR higher 79% of resamples; 2007–09 0.306 vs 0.284 | fails f1, f2; first book above the pin on both CAGR and DD in honest form |
| 75 | Stop proceeds parked in gold (stop10, g10s10) | 1.243 / 1.224; tranches 1.340 / 1.350 | f2; worse than cash parking — gold fell in Mar 2020 and 2022 |
| 76 | Trailing 10% / 15% stop; stop widened to 4.5σ for volatile names (Kaminski & Lo 2014) | trail10 tranches 1.501 (25.2% CAGR, 16.8% DD); trail15 1.393; vol45 1.310 | f1, f2; none beats the fixed 10% stop (1.513) |
| 77 | Tighter stops 7.5% / 5% | 1.523 / 1.647; tranches 1.551 (24.7% CAGR, 15.9% DD) / 1.485 (21.4%, 14.4%) | f1, f2; return falls as fast as drawdown |
| 78 | 10% stop in both sleeves of the half rotation blend (pin or gold-0.10 book) | half_s10 tranches **1.542 (26.9% CAGR, 17.5% DD), 2007–09 0.716**; half_g10s10 tranches 1.528 (28.9%, 18.9%) | f2 at offset 0; best all-round books; bootstrap Calmar > pin tranches 83% |
| 79 | Stop only while the market (NIFTYBEES) is below its rebalance open (g 0 / 5%) | tranches 1.511 (27.3% CAGR) / 1.432 (28.3%) | f1, f2; little different from the plain stop |
| 80 | M61 (top 20 half blend) with 10% stops in both sleeves | 1.416; tranches 1.514 (27.6% CAGR, 18.2% DD) | f2; no better than M78 |
| 81 | 10% stop, proceeds re-spread over the held names | 1.170 | everywhere; worse than cash |
| 82 | 10% stop with re-entry at the reference price (Kaminski & Lo 2014) | 1.324 | f1, f2; same as the plain stop. The name stop never lowers 2010–17 drawdowns, only CAGR |
| 83 | M21's book stop (10 / 15%) on the current pin | 1.423 / 1.038; bstop10 tranches 1.365 (28.3% CAGR, 20.8% DD) | f1, f2 (bstop10); whipsaws in 2016 as in M21 |
| 84 | Frog in the pan (M10 rule, 2 × top_n) on the current pin (Da, Gurun & Warachka 2014) | 0.963; tranches 0.943 | wins f1, f2; loses f3 badly (28.8% vs 35.5% CAGR). Pin's f2 is 2.070, not 2.072 (no verdict changes) |
| 85 | 10% stop on the stitched out-of-sample walk-forward 2014–23 (information) | **half + stop tranches 1.543 (26.1% CAGR, 16.9% DD)** vs book 0.956, half 1.159 | wins every piece | the stop's gain holds out of sample; M78's form is the best OOS book |
| 86 | No gold + 10% stop; and its half blend | 1.329 / 1.289; tranches **1.509 (32.8% CAGR, 21.7% DD)** / 1.501 (30.3%, 20.2%) | f1, f2; g0s10 loses 55% in 2008 (0.248) | gold covers slow bears, the stop fast crashes |
| 87 | Stop sells on lower-circuit days (realism, information) | stop books lose 0.1–0.35 pts CAGR a year vs the pin's 0.08 | — | no conclusion changes; live stop sells must retry |
| 88 | No-gold stop book + 200-day NIFTYBEES filter (risk-off 0 / 0.5, cash) | 1.793 / **1.928**; tranches 1.692 / 1.698 | f1 (2011 whipsaw, no gold) | |
| 89 | M88 with the risk-off share in GOLDBEES | **r50g 1.991 (34.0% CAGR, 17.1% DD)**; r0g 1.534; tranches **1.788 / 1.885** (32.4% / 31.6% CAGR) | f1 only (1.479 vs 1.598) | best family found; beats the pin's CAGR in every fold |
| 90 | M89 robustness: neighbours, bootstrap, stitched walk-forward (information) | r50g neighbours 1.66–1.81 in tranches; bootstrap 87% vs pin; stitched OOS **1.877 (34.1% CAGR, 18.2% DD)** | — | r50g robust; r0g fragile at 150 days |
| 91 | M89 r50g plus fixed gold 0.10 / 0.25 | **2.017** (31.5% CAGR, 15.6% DD) / 1.872; tranches 1.800 / 1.748 | g10: f1 (1.578 vs 1.598), f2; g25: f2 | fixed gold trades fold 1 against fold 2 |
| 92 | Trailing stop in r50g / g10 r50g | 1.807 / 1.829 | f1, f2; worse than the fixed stop | |
| 93 | M91's fixed gold held only while gold trends up (252 sessions, M22) | g10 1.934 (f1 1.594, f2 2.055); g25 1.837; **g25 tranches 1.721 (28.5% CAGR, 16.5% DD; 1.627 / 2.413 / 1.969)** | offset 0: g10 f1, f2 by a hair; g25 f2. g25 tranches beat the pin everywhere but fail 25 bps on f1 (1.481 vs 1.498); no 2007–09 | first tranche book above the pin on every fold |
| 94 | M93 g25gt robustness: neighbours, bootstrap, stitched (information) | neighbours' tranches 1.68–1.94 (189 sessions 1.944); bootstrap 86.5% vs pin; stitched tranches 1.773 (29.7% CAGR, 16.7% DD) | — | fold 1 edge fragile (2 of 4 neighbours lose it); r50g earns ~4 pts more at the same Calmar |
| 95 | 200-day filter on JUNIORBEES (Nifty Next 50) instead of NIFTYBEES, in r50g and g25gt | r50g_jr 1.614 (offset 0); **tranches 1.656 (33.4% CAGR, 20.2% DD; 1.784 / 2.731 / 1.763), 25 bps 1.497 (1.624 / 2.495 / 1.584), 2007–09 0.591** | offset 0 fails f2; **r50g_jr tranches pass the bar, also at 25 bps** | first pass in any form; built in sample over M86–M95 |
| 96 | r50g_jr robustness: neighbours, bootstrap, stitched (information) | neighbours' tranches 1.61–1.89; bootstrap **92% Calmar / 98% CAGR above pin tranches**; stitched tranches 1.661 (33.9% CAGR, 20.4% DD) | 3 of 5 settings pass (150 days and ¼-to-gold miss f1) | strongest candidate; f1 is the fragile fold |
| 97 | Graded filter: a quarter to gold per index (Nifty 50, Next 50) below its 200-day average | 1.785 (34.4% CAGR, 19.3% DD); tranches 1.726 | f1 (1.570 vs 1.598; tranches 1.569 vs 1.590) | between M89 and M95; passes f2 at offset 0 |
| 98 | Top 20 in r50g_jr | 1.576 (offset 0); **tranches 1.603 (34.3% CAGR, 21.4% DD; 1.740 / 2.378 / 1.774); 25 bps 1.451; 2007–09 0.660** | offset 0 f2; **tranches pass, also at 25 bps** | more return, a bit less Calmar than M95 |
| 99 | Filter on breadth (half the universe above its own 200-day average; Zweig 1986) | 1.565; tranches 1.608 (32.7% CAGR, 20.3% DD) | offset 0 f1; tranches f2 vs the pin's tranches (2.189 vs 2.199) | worse than the Next 50 filter |
| 100 | 10% trend gold on the Next 50 filtered book | 1.597; tranches 1.644 (31.8% CAGR, 19.4% DD) | offset 0 f2; tranches pass | passes, but trades CAGR for drawdown; not better than M95 |

What the evidence says so far:

- The max drawdown of every long-only book is March 2020, a one-month crash a monthly rule cannot react to. Calmar is
  roughly CAGR / (that loss). Gold is the only asset with history from 2007 that did not fall with Indian stocks;
  gilt ETFs start in 2016, MON100 trades at a 10–30% premium to NAV.
- Ways that cut the 2020 loss (rotation, low-vol) cost about the same share of return in strong years.
- Timing luck alone moves Calmar by ±0.2 between month-end and a few days earlier.
