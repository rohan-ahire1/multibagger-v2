# Overnight research, 2026-10-02 (M53–M90)

Branch `m43-paper-delivery`, all committed, nothing pushed. Detail in `docs/research/m53.md` … `m90.md` and the log
`docs/research/calmar-search.md`.

## Bottom line

- **New best (M89/M90): no fixed gold + 10% stop + 200-day market filter that moves half the book to gold when
  Nifty is below its 200-day average** (`momentum/m89_g0s10_r50g_b2`, run 20261002-033400-ad917eb0): **34.0% CAGR,
  17.1% max DD, Calmar 1.991** (pin: 29.3%, 26.1%, 1.125). Higher CAGR than the pin in every fold. In four-day form
  (`blend/m89_g0s10_r50g_tranche_b2`, run 20261002-033648-41f7067c): 32.4% CAGR, 18.1% DD, 1.788. It passes every
  check (other decision days, 25 bps, 2007–09, neighbours 150/250 days) **except fold 1** (2010–13: 1.479 vs 1.598;
  it earns more, 22.8% vs 20.9%, but its drawdown is 15.4% vs 13.1%). Bootstrap: Calmar above the pin's in 87% of
  resamples. On the stitched walk-forward (settings tuned only on earlier years) it makes 34.1% CAGR at 18.2% DD
  (1.877) vs 0.956 for the plain book. Caveat: the rule itself was chosen after seeing 2010–23, so the only clean tests
  left are 2007–09 (0.549 vs the pin's 0.284) and the locked 2024+ period. Paper code does not support it yet.
- **The pin is unchanged: `momentum/m49_b_b2`**, 29.3% CAGR, 26.1% max DD, Calmar 1.125 (run 20261002-000607-0103cc7f;
  re-verified exactly). Nothing passed the full bar (beat the pin on 2010–23 and on each fold).
- **Best result found: M61** = half "top 20" stock book + half "top 20 book or gold" rotation
  (`blend/m61_half_top20_b2`, run 20261002-003634-96a48489): **32.4% CAGR, 24.7% max DD, Calmar 1.313**. It fails only
  fold 2 (2014–17: 1.72 vs the pin's 2.07). In the 2008 crash window it more than doubles the pin's Calmar.
- Realistic expectation for any of these books going forward: Calmar about 0.95–1.10, lower if the book is large.

- **Closest to a pass: the half blend (M59) split over four decision days** (`blend/m68_half_tranche_b2`, run
  20261002-010041-4c963e79): 29.4% CAGR, 25.0% DD, Calmar 1.176, folds 1.69 / 2.15 / 1.38. That beats the pinned run on
  the whole period and on every fold, and scores 0.617 vs 0.284 on 2007–09. Three reasons it is not adopted: it was
  pre-registered as information only (M68); its fold 2 trails the pin's own four-day form (2.149 vs 2.199); and at
  25 bps it misses the pin in f2 and f3 by 0.01–0.02 (M69).

- **Strongest out-of-sample evidence: M70.** On M52's walk-forward for 2014–23, where each period uses only settings
  tuned on earlier years, adding the half-rotation rule lifts Calmar from 0.953 to **1.202**. CAGR rises from 24.8%
  to 28.4%, and max DD falls from 26.1% to 23.6%. In four-day form it is 1.159 vs 0.956. The pin's own 2010–17 numbers
  are in-sample (tuned on those years), which is why the strict bar keeps favouring it.

- **New since M70: a 10% stop-loss is the biggest single lever found (M72–M76).** A held stock that closes 10%
  below its price at the last rebalance is sold next morning; the cash waits for the next month-end (Han, Zhou & Zhu
  2016). It fails the strict bar (it loses 2010–13 and 2014–17 to the pin at the pinned decision day), but in
  four-day form:

  | Four-day (tranche) form, 2010–23 | CAGR | Max DD | Calmar | Folds | 25 bps | 2007–09 |
  |---|---|---|---|---|---|---|
  | Pin tranches (`m54_b_tranche_b2`, run 20261002-001643-d6a3c453) | 29.46% | 26.65% | 1.105 | 1.59 / 2.20 / 1.31 | 1.059 | 0.284 |
  | Pin + 10% stop (`m73_stop10_tranche_b2`, run 20261002-013320-14cd39db) | 26.92% | 17.79% | 1.513 | 1.49 / 2.14 / 1.77 | 1.414 | 0.415 |
  | **Gold 0.10 + 10% stop** (`m74_g10s10_tranche_b2`, run 20261002-014019-8df01261) | **30.45%** | **20.12%** | **1.514** | 1.34 / 1.96 / 1.75 | 1.401 | 0.306 |
  | Trailing 10% stop (`m76_trail10_tranche_b2`, run 20261002-020004-78ab2b2d) | 25.21% | 16.80% | 1.501 | 1.45 / 2.07 / 1.74 | 1.387 | 0.506 |

  **Gold 0.10 + stop is the first book with both more return and a smaller drawdown than the pin** (pin has gold 0.25,
  no stop). Bootstrap against the pin tranches: Calmar higher in 82% of resamples, CAGR higher in 79%. Its weak spot is
  2008 (about the pin's ~50% loss). The plain stop costs about 2.5 points of CAGR (correction: an earlier status said
  "same return"; it is 26.9% vs 29.5%), mostly in 2021. Things that did not help the stop: parking stopped money in
  gold (M75: gold fell too in March 2020 and 2022), stops of 15–20%, top 20 instead of 25, widening stops for volatile
  names (M76). The paper code does not support the stop yet.
- **Strongest all-round book: M78, the half blend with a 10% stop in both sleeves, run in four-day form**
  (`blend/m78_half_s10_tranche_b2`, run 20261002-022319-f4c291ea): 26.9% CAGR, **17.5% max DD, Calmar 1.542**,
  folds 1.62 / 2.08 / 1.78, 2007–09 **0.716** (32% DD vs the pin's 51%). It beats the pinned run on the whole period
  and every fold. It is not adopted only because my pre-registered rule asks the four-day form to beat the pin's own
  four-day form (f2 2.080 vs 2.199) and to hold at 25 bps (f1, f2 lose by 0.03). Cost: about 2.5 points of CAGR a
  year vs the pin. Bootstrap: Calmar higher than the pin's four-day form in 83% of resamples. The gold-0.10 version
  (`m78_half_g10s10_tranche_b2`, run 20261002-021723-766fcdd6) keeps more return: 28.9% CAGR, 18.9% DD, 1.528, 2007–09
  0.617.
- **Out of sample, the stop holds up (M85).** On M52's walk-forward (2014–23, each period using only settings chosen
  from earlier years), the half blend + 10% stop in four-day form scores Calmar **1.543** (26.1% CAGR, 16.9% DD) vs
  0.956 for the plain book and 1.159 for the half blend without stops. It wins each of the three periods.
- **Highest return with Calmar ≥ 1.5 (M86): no gold + 10% stop in four-day form** (`blend/m86_g0s10_tranche_b2`, run
  20261002-031020-c087b363): **32.8% CAGR**, 21.7% DD, 1.509. But it loses 55% in 2008 (the stop resets each month, so
  it does not stop a slow bear). Gold handles slow bears, the stop handles fast crashes. Its half blend
  (`m86_half_g0s10_tranche_b2`): 30.3% CAGR, 20.2% DD, 1.501, 2008 loss 39%.
- Also tried and failed (M79–M84): stop only in falling markets, re-buying with stop money, re-entry after recovery,
  a whole-book stop, and ranking on smooth ("frog-in-the-pan") momentum. The stop's gain comes almost all from 2020.
- M71: the 90/10 pin/rotation blend passes the main bar by hairs (1.155) but fails in four-day form; not adopted.
  M72: other one-change overlays on the pin (sector cap 5, residual momentum, 52-week high, absolute momentum, max
  filter) all fail.

## Your decision: pin or M61

| | Pin `m49_b_b2` | M61 `m61_half_top20_b2` |
|---|---|---|
| 2010–23 CAGR / max DD / Calmar | 29.3% / 26.1% / 1.125 | **32.4% / 24.7% / 1.313** |
| Folds 2010–13 / 2014–17 / 2018–23 | 1.60 / **2.07** / 1.36 | 1.81 / 1.72 / 1.67 |
| Other decision days (5 / 10 / 15 sessions before month-end) | 1.10 / 1.06 / 1.14 | 0.96 / 1.18 / 1.18 |
| Same book split over 4 decision days (M54 / M62) | 1.105 | **1.201** (30.4% CAGR, 25.3% DD) |
| Costs at 25 bps a side | 1.078 | **1.229** |
| 2007–09, never used to choose (mean of 4 decision days) | 0.28, ~51% DD | **0.63–0.64, ~40% DD** |
| After trading impact at ₹10 lakh / ₹50 lakh / ₹2 crore (M65) | 1.10 / 1.07 / 1.01 | **1.27 / 1.22 / 1.13** |
| Bootstrap: M61 split over 4 days beats the pin split over 4 days | | 59% of resamples (weak) |
| Trades 2010–23 | 1,276 | 2,224 |

**Recommendation (updated after M70): the half blend (50% pin + 50% pin-or-gold rotation), run split over the
four decision days.** It has the best out-of-sample record (M70 walk-forward, 2007–09) and stays close to the pin in
bull years. M61 is the higher-return version (top 20), but top 20 is itself a search pick. Original note: M61 or the half blend, run split over the four decision days (the M62 form), if you accept a book that loses in
strong bull years like 2014–17 in exchange for better crash protection. The 2010–23 edge alone is mostly noise
(59%); the real case is 2007–09, a window no search ever saw, where M61 lost ~40% against the pin's ~51%. If you
want to keep the strict rule, stay on the pin. Either way, the paper book needs your OK, and the M61 rotation is not
yet supported by the paper code (`check_supported` refuses it).

## What was tried overnight (all fail the bar)

| # | Idea | Calmar vs pin 1.125 | Why it fails |
|---|---|---|---|
| 53 | Drop names whose delivered volume dried up (Gervais et al. 2001) | 1.081 | whole period |
| 54 | Pin split over 4 decision days | 1.105 | the timing-luck-free pin; same drawdowns |
| 55 | Rank on daytime- or overnight-only returns (Lou, Polk & Skouras 2019) | 0.736 / 0.599 | everywhere |
| 56 | Hold buffer 35 / no resizing (Novy-Marx & Velikov 2016) | 1.214 | loses 3 other decision days |
| 57 | Decide every 5 or 10 sessions | ≤ 1.115 | whole period |
| 58 | Top 20 | 1.193 | fold 2 only |
| 59 | Book-or-gold rotation, half and half with the pin | 1.279 | fold 2 only |
| 60 | Delivery filter 0.85 | 1.024 | 0.80 is the peak |
| 61 | Top 20 + half rotation | **1.313** | fold 2 only |
| 63 | Slower rotation signal | 1.267 | fold 2; no better than M61 |
| 64 | Top 15 | 1.161 | fold 2; concentration peaks at 15–20 |
| 66 | Liquidity floor ₹50 lakh | 1.164 | fold 1 |
| 67 | Lookback ensemble 189 / 273 / 378 | 1.076 | everywhere |
| 71 | Pin/rotation blend 90/10 and 80/20 | 1.155 / 1.185 | 90/10 fails in four-day form; 80/20 at 25 bps |
| 72 | One overlay on the pin: sector cap 5, residual momentum, 52-week high, absolute momentum, max filter, 10% stop | 1.122 / 0.991 / 0.769 / 1.026 / 1.115 / **1.346** | stop: f1, f2 |
| 73 | Stop 10 / 15 / 20% | 1.346 / 1.239 / 1.176 | f1, f2 |
| 74 | Stop + top 20; stop + gold 0.10 | 1.387 / 1.336 | f1, f2 |
| 75 | Stop proceeds parked in gold | 1.243 / 1.224 | worse than cash |
| 76 | Trailing 10 / 15% stop; volatility-widened stop | 1.397 / 1.227 / 1.132 | f1, f2 |
| 77 | Tighter stops 7.5% / 5% | 1.523 / 1.647 | f1, f2; return falls with drawdown |
| 78 | Stop in both sleeves of the half blend | 1.284 / 1.292 | f2 (four-day form beats the pinned run; see above) |
| 79 | Stop only in a falling market | 1.251 / 1.365 | f1, f2 |
| 80 | Stop + top 20, and its rotation | 1.416 | f2 |
| 81 | Re-spread stop money into held names | 1.170 | everywhere |
| 82 | Re-buy a stopped name once it recovers | 1.324 | f1, f2 |
| 83 | Whole-book stop 10 / 15% | 1.423 / 1.038 | f1, f2 |
| 84 | Frog-in-the-pan ranking | 0.963 | f3 |
| 86 | No gold + stop; its half blend | 1.329 / 1.289 | f1, f2; 55% loss in 2008 |
| 88 | No-gold stop book + 200-day filter (to cash) | 1.793 / 1.928 | f1 (2011: cash, while gold rose) |
| 89 | Same, risk-off share in gold | 1.534 / **1.991** | f1 only (r50g) |

Information only: M87 (stop sells on lower-circuit days cost 0.1–0.35 pts CAGR a year), M90 (M89 robustness, above), M85 (stop on the out-of-sample walk-forward, above), M62 (M61 in decision-day tranches), M65 (trading impact by book size), M68 (all near-misses in
tranches: half 1.176, M61 1.201, top 20 1.145, pin 1.105), M69 (tranche books at 25 bps: half 1.100, M61 1.121,
pin 1.059).

## Why nothing passes

Fold 2 (2014–17) was momentum's best stretch, and the pin is already near the best possible there. Every defensive
idea (gold rotation, trend filters, volatility rules) gives up return in that fold: the 2015–16 fall and the
demonetisation drop (Nov 2016) were short, so switching out cost more than it saved. Every concentration idea lifts
2010–13 and 2018–23 but deepens fold-2 drawdowns.

## Still open (your call)

0. **New first choice: M89 r50g** (above), in four-day form. It needs a rule decision (fails fold 1 by drawdown) and
   paper-code support for the stop and the gold switch.
1. Pin vs M61 vs the half blend vs the stop books, each run in four decision-day tranches (above). My pick now: the
   half blend with 10% stops (M78) if you accept ~2.5 points less CAGR for a drawdown of 17.5% instead of 26.7% and a
   much better 2008; gold 0.10 + stop (M74) if you want the pin's return with a smaller drawdown. Both need a rule
   decision (they beat the pinned run, not the pin's four-day form in 2014–17) and paper-code support for the stop. The half blend is the
   conservative choice: it gives up 1 point of CAGR against M61 but wins fold 2 and trades less.
2. The one-time `--final` test on the locked 2024–26 period, for whichever you pick.
3. Paper deployment of the chosen book (needs your OK; M61 needs paper-code support for the rotation first).
4. Nothing is pushed.
