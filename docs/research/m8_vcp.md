# M8 question 2: Minervini's VCP, built to his rules

Status: **rules accepted as drafted (2026-09-29); detector built (`src/mb/strategy/vcp/`); pattern check done in two
rounds, two rules added (2026-09-29). No backtest yet.** Sources: Minervini, *Trade Like a Stock Market Wizard* (2013)
and *Think & Trade Like a Champion* (2017). Price and volume rules only; the earnings half of SEPA is left out (no
earnings data yet) and added later only if the pattern shows promise.

## Why v1 was not really a VCP

From `strategies/sepa/configs/v1_port_dev_b.yaml` and `src/mb/strategy/sepa/signals.py`:

| Rule | Minervini | v1 port |
|---|---|---|
| Distance from 52-week high | within 25% | within 45% |
| Distance above 52-week low | at least 30% | at least 10% |
| Relative strength | 12-month, latest quarter weighted double, rank ≥ 70 | 3-month return vs NIFTYBEES, rank ≥ 70 |
| Contractions | 2–6, each shallower than the last | at most 2, counted from a smoothed 10-day range; depth never checked |
| Base depth | usually 10–35% | up to 60% |
| Pivot | high of the last, tightest contraction | highest high of the last 65 sessions |
| Breakout volume | at least 40–50% above average | at least average (1.0x) |
| Volume dry-up | volume shrinks through the base, very low in the last contraction | 10-day / 50-day volume ≤ 0.9 on the day before |
| Other | none | no January trades, 10-day range ≤ 8% |

So v1 mostly traded any stock breaking a 3-month high in a loose uptrend. That also explains its low signal count: the
filters stacked on top (range ≤ 8%, dry-up ≤ 0.9, ≤ 2 contractions) cut about 70% of what was left, for reasons
unrelated to the pattern.

## Proposed rules

Every number below becomes a config value. Numbers in **bold** are my reading of the books and are the ones to check.

### 1. Universe

EQ series; raw close ≥ ₹50; 50-session average ₹ turnover ≥ ₹5 cr (as in momentum); at least 252 sessions of history.

### 2. Trend template (all eight, on the close of the day before the breakout)

1. Close > 150-day and 200-day SMA.
2. 150-day SMA > 200-day SMA.
3. 200-day SMA higher than it was 21 sessions ago (one month).
4. 50-day SMA > 150-day and 200-day SMA.
5. Close > 50-day SMA.
6. Close ≥ 1.30 × 52-week low.
7. Close ≥ 0.75 × 52-week high.
8. RS rank ≥ **70**.

### 3. Relative strength rank

Score = 0.4 × 63-session return + 0.2 × 126-session return + 0.2 × 189-session return + 0.2 × 252-session return
(the usual approximation of IBD's rating, with the latest quarter counted twice). Rank it daily as a percentile 1–99
among all universe stocks.

### 4. Finding the swings

A **swing high** is a session whose high is the highest of the **5** sessions on each side; a **swing low** likewise
with lows. A swing is only known 5 sessions after it happens, so nothing looks ahead. Consecutive highs keep the
higher one and consecutive lows keep the lower one, so highs and lows alternate.

### 5. The base and its contractions

- **Base start:** the highest swing high in the last 325 sessions (65 weeks). No later high may exceed it.
- **Base length:** 15 to 325 sessions (3 to 65 weeks) from the base start to the breakout.
- **A contraction** runs from a swing high to the lowest low before the next swing high. Its depth is (high − low) / high.
  The last contraction runs from the last swing high to the day before the breakout.
- **Count:** 2 to 6 contractions.
- **Each shallower:** every contraction's depth is less than the one before it.
- **First contraction** at most **35%** deep; **last** at most **10%**.
- **Overall tightening:** the last contraction is at most **0.67** × the first (added after round 1).
- **Pivot high near the top:** the last swing high (the pivot) is at least **0.85** × the base start high.

### 6. Volume dry-up

- Average daily volume in the last contraction is below the average in the first contraction.
- At least one session in the last contraction trades below **0.5** × the 50-session average volume.

### 7. Breakout and entry

- **Pivot** = the high of the last swing high.
- **Signal:** the day's close is above the pivot, no close since the pivot high was (added after round 1: only the
  first close through the pivot counts), and volume is at least **1.4** × the 50-session average (40% above).
- **Entry:** next session's open, skipped if that open is more than **5%** above the pivot (Minervini: don't chase).

### 8. Stop, sizing, exits

- **Initial stop:** the low of the last contraction, but never more than **8%** below the entry (his hard maximum is
  10%; his average loss is 6–7%).
- **Sizing:** risk **1.25%** of equity per trade, at most **20%** of equity in one name, at most **10** positions.
- **Breakeven:** once the close is **2 R** above entry, the stop moves to entry.
- **Trailing exit:** after that, sell at the next open when the close falls below the **50-day SMA**. This needs one new
  engine exit mode.

## Before any backtest: the pattern check

1. **Funnel.** For 2010–2023, per year: stock-days passing the trend template → with a valid base → with volume dry-up →
   breakouts. This shows where signals disappear.
2. **Charts.** 30 randomly sampled breakouts, each drawn with its swings, contractions, pivot and volume, plus 10 known
   textbook VCPs if you have examples in mind. You judge by eye whether they are real VCPs. If they aren't, the swing
   rules change and the charts are redrawn; still no returns looked at.

Returns are only computed once you are happy with the charts.

### Round 1 (config `strategies/vcp/configs/vcp_dev.yaml`, hash b2cfbe2f, dataset `nse_research@2026-09-29d`)

`uv run mb vcp check strategies/vcp/configs/vcp_dev.yaml --sample 30 --seed 1` → `reports/vcp-check/vcp_dev_round1/`.

| Stage | Stock-days, 2010–2023 |
|---|---|
| Passed the trend template the day before | 257,406 |
| Valid base | 16,813 |
| Volume dry-up | 13,159 |
| Breakout | 521 (361 symbols; 8 in 2012 to 101 in 2023) |

Most days fail the base because price is still above the base's first high (101,931) or the base is under 15 sessions
(65,328). Breakouts by contraction count: 2 → 377, 3 → 110, 4 → 25, 5 → 8, 6 → 1.

Implementation notes:
- The engine's fill-relative rules are in `EngineConfigVCP` (older configs keep their hash): an open more than 5% above
  the pivot drops the signal (`skipped_chase`), and the stop is raised to 8% below the actual fill.
- Contractions are measured from each swing high to the lowest low before the next swing high; equal highs keep the
  first; two highs in a row keep the higher. A swing is only used once its 5 right-hand sessions have closed.

Chart review (Claude's judgment, 30 charts): **16 clear VCPs, 7 marginal, 7 not VCPs.** The seven failures: BGRENERGY
(13% → 10%, one-day shakeout), INDIANB (loose final area), KIRLOSENG (14% → 13% → 6%, choppy), MARKSANS (9% → 8% with a
lower low), RNAM (V-shaped crash), SOBHA (wide and loose), ZENSARTECH (had already closed above the pivot days earlier).

Two faults explain most of them, and both are measurable across all 521 breakouts:
- **Stale pivot** (49 breakouts): price had already closed above the pivot earlier, so the "breakout" was a second
  attempt. Minervini buys the first move through the pivot.
- **No real tightening** (48 breakouts): the last contraction was more than 0.67 × the first. No chart judged a clear
  VCP had a ratio above 0.615.

Together these drop 93 of 521. Both became rules (`not_tightening`, `pivot_already_crossed`).

Rules tested on round 1 and **not** adopted:
- Each contraction at most 0.75 × the one before (used by several screeners): drops good charts where two middle
  contractions are similar.
- Higher lows through the base: only one failed chart had a lower low.
- Daily-range tightness (mean range of the last 10 sessions / mean range in the first contraction): failed charts sat at
  0.63–0.96 but clear VCPs spread 0.48–1.10, so a cut at 0.70 drops about 8 good charts.

Known weakness, not fixed: the 5-session swing sometimes misses the true tight final area (FINCABLES, SRTRANSFIN), so
the last contraction starts earlier than the eye would put it and the stop is wider.

### Round 2 (hash 5737198e, same dataset, fresh sample)

`uv run mb vcp check strategies/vcp/configs/vcp_dev.yaml --sample 30 --seed 2` → `reports/vcp-check/vcp_dev/`.

| Stage | Stock-days, 2010–2023 |
|---|---|
| Passed the trend template the day before | 257,406 |
| Valid base | 14,722 |
| Volume dry-up | 11,678 |
| Breakout | 428 (318 symbols; 8 in 2011 and 2012 to 85 in 2023) |

The new rules removed 2,091 days as `not_tightening` and 2,385 as `pivot_already_crossed`.

Chart review, different random sample: **22 clear VCPs, 6 marginal, 2 not VCPs** (round 1: 16 / 7 / 7).
- Not VCPs: IBVENTURES (22% → 18% → 8%, second low below the first, pivot 10% under the base high, flat 50-day SMA),
  PRICOLLTD (wide spiky bars; the last contraction is a one-day shakeout).
- Marginal: DPWIRES (weak close on the breakout day), GICHSGFIN and METROBRAND (pivot 9–12% under the base high), IRFC
  (lower low in the middle), SHAKTIPUMP (last contraction 10%, stop 9.8% away), SIEMENS (last contraction a one-day drop).
- Clear examples: TATAELXSI 2021 (17% → 5% → 4%), FILATEX 2021 (23% → 14% → 7%), MOTHERSUMI 2021 (21% → 11% → 7%),
  VIJAYABANK 2017 (15% → 9% → 6%).

Checked and not adopted: raising the pivot floor from 0.85 to 0.90 of the base high. Clear VCPs sit at 0.875–0.90 too
(BALRAMCHIN, DIXON, BAJAJFINSV), so it would cut good charts along with the marginal ones.

Verdict: the detector now finds real VCPs about three times in four, and nearly all of the rest are borderline, not
wrong. Good enough to backtest.

### What the research says (checked 2026-09-29)

Minervini's own numbers, as restated by practitioners and open-source screeners, match the rules above:
- Base 3–65 weeks; 2–6 contractions, usually 2–4, each roughly half the one before; first usually 10–35%, last 3–10%.
- Volume dries up to the base's lowest in the final contraction ("so low you wonder if trading halted"), for several
  quiet days.
- Breakout: close above the pivot (high of the last contraction) on volume at least 40–50% above the 50-day average.
  Stop under the last contraction's low.
- Failure signs: contractions that widen, heavy-volume selling inside the base, a weak-volume breakout that falls back.
- Screeners (tradermonty, phuazz) add a per-step ratio of at most 0.75 and a first contraction of at least ~8%; we
  tested the ratio and rejected it (above).

Sources: [luxalgo concept](https://www.luxalgo.com/library/concept/volatility-contraction-pattern/),
[luxalgo indicator](https://www.luxalgo.com/library/indicator/volatility-contraction-pattern/),
[tradermonty vcp-screener](https://tradermonty.github.io/claude-trading-skills/en/skills/vcp-screener/),
[phuazz/vcp-screener](https://github.com/phuazz/vcp-screener),
[finermarketpoints checklist](https://www.finermarketpoints.com/post/vcp-criteria-complete-checklist),
[elearnmarkets](https://www.elearnmarkets.com/school/units/trade-like-a-stock-market-wizard/a-picture-is-worth-a-million-dollars),
[deepvue](https://deepvue.com/screener/volatility-contraction-pattern/),
[tradingsim](https://www.tradingsim.com/blog/volatility-contraction-pattern).

## Backtest plan (after the charts pass)

Development period only, dataset `nse_research@2026-09-29d`, question tag `vcp`. Pin to beat: `sepa/v1_port_dev_b`
(Calmar 0.26); adoption also needs both baselines beaten on every fold. Fixed variants, no others:

| Config | Change |
|---|---|
| `vcp_dev` | The rules above |
| `vcp_market_dev` | Plus: no new entries while NIFTYBEES fails its own trend template rules 1–5 (Minervini avoids buying in a downtrend) |
| `vcp_intraday_dev` | Enter on a buy-stop at the pivot during the day instead (his actual entry), with no volume check, since daily data can't see volume at the moment of the breakout |

Honest expectation: VCP holds cash most of the time, so on its own it likely won't beat vol-adjusted momentum's Calmar.
Its likely value is as a second book beside momentum; that comparison is a separate, later question.

## Open questions

1. Swing size of 5 sessions each side misses some tight final areas; 3 sessions may fit better but gives noisier
   swings. Not changed yet.
