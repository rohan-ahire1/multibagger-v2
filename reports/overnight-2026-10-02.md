# Overnight research, 2026-10-02 (M53–M70)

Branch `m43-paper-delivery`, all committed, nothing pushed. Detail in `docs/research/m53.md` … `m67.md` and the log
`docs/research/calmar-search.md`.

## Bottom line

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

## Your decision: pin or M61

| | Pin `m49_b_b2` | M61 `m61_half_top20_b2` |
|---|---|---|
| 2010–23 CAGR / max DD / Calmar | 29.3% / 26.1% / 1.125 | **32.4% / 24.7% / 1.313** |
| Folds 2010–13 / 2014–17 / 2018–23 | 1.60 / **2.07** / 1.36 | 1.81 / 1.72 / 1.67 |
| Other decision days (5 / 10 / 15 sessions late) | 1.10 / 1.06 / 1.14 | 0.96 / 1.18 / 1.18 |
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

Information only: M62 (M61 in decision-day tranches), M65 (trading impact by book size), M68 (all near-misses in
tranches: half 1.176, M61 1.201, top 20 1.145, pin 1.105), M69 (tranche books at 25 bps: half 1.100, M61 1.121,
pin 1.059).

## Why nothing passes

Fold 2 (2014–17) was momentum's best stretch, and the pin is already near the best possible there. Every defensive
idea (gold rotation, trend filters, volatility rules) gives up return in that fold: the 2015–16 fall and the
demonetisation drop (Nov 2016) were short, so switching out cost more than it saved. Every concentration idea lifts
2010–13 and 2018–23 but deepens fold-2 drawdowns.

## Still open (your call)

1. Pin vs M61 vs the half blend, each run in four decision-day tranches (above). The half blend is the
   conservative choice: it gives up 1 point of CAGR against M61 but wins fold 2 and trades less.
2. The one-time `--final` test on the locked 2024–26 period, for whichever you pick.
3. Paper deployment of the chosen book (needs your OK; M61 needs paper-code support for the rotation first).
4. Nothing is pushed.
