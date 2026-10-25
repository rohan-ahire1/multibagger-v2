# Research loop journal

Newest entry at the bottom. Rules: docs/research/LOOP.md.

## 2026-10-23 start

Loop set up from the Mac session. Branch research = m119-options-book (cae6fb2). Dataset nse_research@2026-10-14. Next free milestone M120.

## 2026-10-22, cycle 1: M120 limit-hit filter

Research (web): Indian momentum papers (Singh et al. 2022 risk-managed momentum, BSE; "Momentum, reversals and
liquidity: Indian evidence" 2023, PBFJ; Raju 2024 "Shades of Momentum", SSRN 4977717: vol-adjusted and information
discreteness best in India, both already in or dead here); Li, Zhang & Zheng 2018 (Heston-Sadka seasonality weak in
emerging markets: dropped); industry momentum (no India evidence found: parked); promoter pledges and crash risk
(Kalia 2024 JAMR; Chauhan, Mishra & Spahr 2021 FM: real evidence, but needs a pledge-history feed: queued);
NSE ASM surveillance list (Chari & Inamdar, NSE working paper: prices stabilise after inclusion; needs ASM history:
queued); price-limit lottery measures (Yao et al. 2021 IREF China, Wang & Lien 2022 RQFA Taiwan, Lin, Qiu & Zheng 2023
JBF) plus the Indian practitioner rule "skip stocks with more than 20 circuit hits": picked, price-only, untried.
Environment note: this VPS checkout has no `runs/` and no dataset `2026-10-02b`, so M106 references are re-run on
`2026-10-14` (`m120_ref*`), and 3 old tests (m89, m97) fail on the missing dataset (not a code fault).
Result: fail (docs/research/m120.md). lh20 Calmar 1.513 vs 1.500 at offset 0 (after tax 1.133 vs 1.102), but loses
offsets 5/10/15 (0.975 / 1.085 / 1.283 vs 1.080 / 1.273 / 1.409) and folds f1, f3; costs ~3.5 pts CAGR, all in the
2020-22 small-cap boom. lh10 worse. Verdict: not adopted; limit-hit / lottery filters join the dead list.
Variants: ~992. Other checks this cycle: NSE pledge API returns only the latest snapshot (no history): pledge idea
blocked unless an archive is found. Barber et al. 2013 earnings-announcement premium: India 0.29%/month, not
significant: weak.
Next queue: (1) long-term reversal guard: skip new buys whose months 13-36 return is extreme (De Bondt-Thaler;
Dhankar & Maheshwari NSE 1997-2013 long-term overreaction; Conrad & Yavuz 2017); (2) industry momentum tilt using the
sector map (Moskowitz & Grinblatt 1999; no India test found); (3) realism: M106 robustness / live-fill checks.

## 2026-10-23, cycle 2: M121 long-term reversal guard

Research: industry momentum dropped for now (sector map covers only the current Nifty 500, 524 symbols, while M106
buys small caps; a point-in-time industry map would be needed). NSE shareholding-pattern history is fetchable
(`/api/corporate-share-holdings-master?symbol=X`, quarterly from Dec 2015, promoter %, submission dates; revisions
overwrite originals), but promoter buying is the dead insider family. Picked: skip new buys in the top 10% / 20% of
month 13-36 returns (De Bondt & Thaler; Jegadeesh & Titman 2001; Conrad & Yavuz 2017; Dhankar & Maheshwari NSE).
Result: fail (docs/research/m121.md). lr10 wins all four offsets, 25 bps and after tax by small margins
(1.535 vs 1.500 at offset 0) but loses f1 (2.126 vs 2.259) and f2 (2.189 vs 2.200); bootstrap only 62.8%. lr20 worse.
Variants: ~994.
Next queue: (1) Cooper-Gutierrez-Hameed market state: JUNIORBEES 36-month return < 0 as a second risk-off condition;
(2) realism / robustness of M106 (live fills vs backtest, cost sensitivity on the newest data).

## 2026-10-23, cycle 3: M122 market state

Idea: also risk-off when JUNIORBEES's 36-month (Cooper, Gutierrez & Hameed 2004) or 24-month (Daniel & Moskowitz 2016)
return is negative. Result: fail (docs/research/m122.md): st36 1.440, st24 1.430 vs 1.500 at offset 0; both lose f1,
f3, 25 bps. st24's wins at offsets 5/10 are timing luck before March 2020. Regime family: the 200-day rule on the
Next 50 is not improved by slower states either. Variants: ~996.
Next: (1) short-term reversal guard at entry: skip new buys whose last ~2 weeks' return is in the top 10% of the ranked
names (Jegadeesh 1990; Lehmann 1990; Chui, Ranganathan, Rohit & Veeraraghavan 2023 PBFJ: short-term reversals in
illiquid Indian stocks); (2) realism / robustness of M106.

## 2026-10-23, cycle 4: M123 short-term reversal guard

Idea: skip new buys in the top 10% / 20% of last-21-session returns (Jegadeesh 1990; Lehmann 1990; Indian large
one-month moves reverse, Economic Thought 2022). Result: fail (docs/research/m123.md): sr20 1.540 vs 1.500 at offset 0
but loses offsets 5/10/15 and f1; sr10 loses offset 0. Signs flip by decision day. Variants: ~998.
Pattern after four cycles (M120-M123): every buy filter on M106 moves Calmar within the ±0.05-0.2 decision-day noise
band; none moves all four offsets and all folds. The buy-side filter family on this book looks exhausted.
Next: switch to robustness/realism of M106 (LOOP step 10): (1) re-check M106's numbers on a dataset extended to the
newest bhavcopy (live window since the locked final); (2) a capacity / impact check at today's paper capital.

## 2026-10-23, cycle 5: M124 no-trade band for resizing

Idea: leave held names alone while within 20% / 50% of their inverse-vol goal (Leland 1999; Donohue & Yip 2003;
Novy-Marx & Velikov 2016; Constantinides 1983 for tax). Result: fail (docs/research/m124.md): band20 1.524 / 1.126
after tax vs 1.500 / 1.102, but loses offset 5 (by 0.003), f1, f2; band50 worse. Tax saved is negligible: M106's tax
comes from exits, not trims. Variants: ~1,000.
Session summary (M120-M124): five ideas, all fail the bar; the best near-misses are M121 lr10 (all offsets, fails
f1/f2) and M124 band20. M106 stays. Next queue: (1) a point-in-time industry map (needed for industry momentum: check
whether NSE's quote API or old bhavcopy-era "industry" files give history); (2) robustness of M106 on newer data;
(3) tax: since exits carry the tax, a rule that defers exits of winners near 12 months (M110 taxhold) was a hair from
passing; any revisit needs a new reason.

## 2026-10-23, cycle 6: M125 industry momentum

Built `mb data fetch industry` (NSE quote API, four-level classes for today's 2,611 listed symbols; snapshot
`data/raw/nse_industry/2026-10-22.parquet`, 90% of M106's buys classified). Idea: no new buys in the weaker half of
sectors / industries by 12-1 momentum (Moskowitz & Grinblatt 1999). Result: fail (docs/research/m125.md): sector wins
all four offsets and 25 bps (1.532 vs 1.500 at offset 0) but loses f1, f2; bootstrap 37%. Industry level ties.
Variants: ~1,002.
Pattern: M121 (long-term reversal) and M125 (sector) both cut drawdown ~0.5-1 pt and pay ~1 pt CAGR in 2010-17;
they win every decision day by small margins and lose f1/f2. Combining them would be fitting the dev period; not done.
Next queue: (1) the M110 taxhold rule was a hair from passing in 2010-23 and slightly negative on the locked years:
closed. (2) M106 robustness on the newest data: extend the dataset (bhavcopy + delivery since 2026-10-14) once the
paper book has a few months; (3) look for new data families: FII/DII holding changes from the shareholding XBRL
(quarterly, from 2015) - check evidence first.

## 2026-10-23, cycle 7: M126 moving-average ensemble

Check first: market costs (configs/market/nse_cash.yaml) match today's delivery charges within 0.00003%; no change.
M106's worst drawdown is the slow 2022 bear (20.1%), then March 2020 (17.7%).
Idea: grade the Next 50 filter over 150/200/250 (or 100-300) SMAs (trend ensembles). Result: fail
(docs/research/m126.md): 1.654 at offset 0 but flat/worse at offsets 5/10/15 and loses f1. The M109 SMA nudges
(160/240 > 200) were month-end timing luck. Variants: ~1,004.
Next queue: offset-0 results keep misleading (M120, M123, M126): pre-screen future ideas at all four offsets first
and skip the after-tax/bootstrap work when they split. Ideas left: FII/DII holding changes (heavy XBRL fetch; check
evidence), realism on the newest data once the paper book has history.

## 2026-10-23, cycle 8: M127 momentum-score tilt

Housekeeping: the three tests needing dataset 2026-10-02b now skip where it is absent (suite: 305 passed, 9 skipped).
Skipped after research: FII/DII holding changes (evidence weak: FIIs chase returns; heavy XBRL fetch).
Idea: tilt weights by the MSCI / Nifty 200 Momentum 30 normalised score (1+Z). Result: fail (docs/research/m127.md):
offset 0 1.413 vs 1.500 (more 2022 drawdown), offsets 5/10/15 higher; +0.7-1.2 pts CAGR at every offset. Pre-screen
at four offsets saved the rest. Variants: ~1,005.
Next queue: ideas on this book are thin. Remaining: (1) risk-off concentration: under risk-off hold the top 12 at full
weight instead of 25 at half (untried form); (2) promoter-holding level from the shareholding master (cheap fetch,
weak evidence); (3) data/realism work.

## 2026-10-23, cycle 9: dispersion timing dropped before pre-registration; session summary

Checked: the M106 paper book (multibagger-v2, data/paper/momentum_b_top25_gold25_jr_gap) runs its daily jobs with no
problems; its first decision is the 2026-10-30 month-end, so there are no live fills to compare yet.
Idea: risk-off also when 3-month cross-sectional return dispersion is in the top 20% of 5 years (Stivers & Sun 2010
JFQA). Dropped at the information stage (no backtest, not counted): the extra risk-off months are 2014-05..2015-10 and
2020-07..2022-01, India's small-cap booms where this book earned most; in India high dispersion marks booms, not
momentum stress.

Session 2026-10-22/23 (M120-M127): 8 ideas pre-registered and tested, 0 passed; variants ~1,005. M106 unchanged and
still the best book on the bar. Lessons:
1. Month-end (offset 0) results mislead often (M120, M123, M126, M127): pre-screen every candidate at all four offsets.
2. Buy filters (limit hits, long/short reversal, industry, reversal) move Calmar inside the ±0.05-0.2 decision-day band.
3. The near-misses (M121 lr10, M125 sec) both cut drawdown ~0.5-1 pt and pay ~1 pt CAGR in 2010-17; bootstrap 37-63%.
4. Tax: most tax comes from exits, not monthly trims (M124).
New tools: `mb data fetch industry` (NSE four-level classes), `notebooks/m120_limits.py report|bootstrap` (any
config@run pair), engine `Target.resize_band`.
Queue for the next session: (1) after 2026-11-30, compare the paper book's first two decisions with research;
(2) promoter-holding level from the shareholding master (cheap, weak evidence); (3) tranche support for paper (would
remove the ±0.2 Calmar month-end luck; needs the user's OK to deploy, research-side code only).

## 2026-10-23, cycle 10: M128 downside-deviation score

Research: Indian momentum (Raju & Chandrasekaran 2019; Pelluri 2025, SSRN 5116091; Vijaykumar 2020) adds nothing new
to M106; BacktestIndia 2026 blog posts: low "scaled turnover" (traded value / market cap) momentum names beat high ones
(19.4% vs 8.5% CAGR, Nifty 200 Momentum 30 split, not peer-reviewed). Dropped: shares outstanding history exists only
for index members (NSE PR archive `ffix*.csv`), not M106's small caps, and delivery share (M40) already covers churn.
Picked: rank on return / downside deviation (Rachev et al. 2007 JBF; Leon, Navarro & Nieto 2016; AEA 2019 partial
moments). Result: fail at the pre-screen (docs/research/m128.md): 1.467 vs 1.500 at offset 0, loses offsets 5 and 15,
wins 10; f2, f3 lost; 0.3-0.5 pts less CAGR everywhere. Variants: ~1,006.
Next queue: (1) risk-off concentration (top 12 at full weight under risk-off instead of 25 at half); (2) realism:
dataset refresh after the first paper decision (2026-10-30).

## 2026-10-23, cycle 11: M129 momentum acceleration

Research: risk-off concentration (no evidence; Taiwan fund study says diversify in bears), aggregate illiquidity state
(Avramov, Cheng & Hameed 2016 JFQA; Indian high-illiquidity months are bottoms before rebounds), weekly regime checks
(56 vs 26 flips, whipsaws, no earlier 2020/2022 exits) and "physical momentum" (arXiv 2302.13245, NSE 500, = the vol
score) all dropped at the information stage (not counted). Picked: acceleration (Ardila, Forró & Sornette 2015; Chen &
Yu, US). Result: fail at the pre-screen (docs/research/m129.md): 1.625 vs 1.500 at offset 0, loses offsets 5/10/15
and f1 (1.41 vs 2.26); -2 to -2.7 pts CAGR everywhere for 1-2 pts less drawdown. Variants: ~1,007.
Pattern holds: ranking changes (M127, M128, M129) trade CAGR for drawdown or win only at month-end.
Next queue: ideas are thin; move to LOOP step 10 work: (1) M106 realism on fills at today's capital (open-auction
liquidity of the small caps it buys); (2) after 2026-10-30, compare the first live decision with research.

## 2026-10-23, cycle 12: M130 fill timing (realism, information)

Research first: Beckmeyer & Wiedemann 2025 JBF ("All days are not created equal": learned weights on past daily
returns; earnings-day, market-jump and large-move returns carry the most information): the earnings-day part is the
dead M114 family in India, and learned weights are an Optuna-style fit; not tried. Bro 2026 SSRN (momentum =
liquidity improvement): no long-only rule to test.
Then LOOP step 10: `notebooks/m130_fill_timing.py` re-simulates M106 with fills at the next close, the next
(O+H+L+C)/4, or one session late. Open reproduces the records. Mean CAGR cost over the four offsets: close −0.49, typical
−0.37, late −0.62 pts; Calmar stays above 1.0 everywhere (docs/research/m130.md). Live (M7): use pre-open AMO orders;
a missed fill should go at the next open. Variants for adoption: unchanged (~1,007).
Next queue: (1) the first live decision on 2026-10-30: compare the paper book's orders with a research run; (2) a
corporate-action audit of 2024-26 for M106's held names (data quality, no returns).

## 2026-10-23, cycle 13: M131 equal-risk-contribution weights

Idea: weight the 25 picks so each adds equal variance (ERC; Maillard, Roncalli & Teiletche 2010; HRP, López de Prado
2016), correlations from 84 sessions, sample or half-shrunk. Result: fail at the pre-screen (docs/research/m131.md):
offset 0 1.357 / 1.441 vs 1.500; offsets 5 and 10 win, 15 ties or loses; f3 lost. Weighting family on this book
(inverse vol, M124 bands, M127 score tilt, M131 ERC) is done. Variants: ~1,009.
Next queue: (1) the first live decision on 2026-10-30: compare the paper book with research (after the 2026-10-30
evening job); (2) data quality for 2024-26 (corporate actions on held names, no returns).

## 2026-10-23, cycle 14: M132 trade-to-trade exit

Checks first: tax model already treats GOLDBEES at slab rates; paper fills on missing opens match the backtest; the
dataset checks and run gate cover unexplained jumps, so no separate 2024-26 audit (would repeat them).
Idea: 55 M106 holdings moved from EQ to BE between decisions in 2010-23 and fell 4% on average before the month-end
exit (info count, disclosed in the pre-registration); Parmar & Chaturvedula 2017 find negative abnormal returns after
trade-for-trade shifts. Rule: sell at the next open after the move. Result: fail at the pre-screen
(docs/research/m132.md): offset 0 1.680 vs 1.500 (DD 18.2%), offset 5 1.084 vs 1.080, but offsets 10 / 15 lose
(1.271 / 1.378) and f1/f2 by < 0.01. Variants: ~1,010.
Note for M7 (live): even without adoption, a held stock moved to trade-to-trade needs care live (delivery only,
narrow band); flag it in the daily ticket. Not changed in the running paper book (LOOP rule).
Next queue: (1) 2026-10-30 first live decision vs research; (2) ideas are thin; next research pass should look at
new data families only (shareholding pattern quarterly history is the one cheap source left).

## 2026-10-23, cycle 15: M133 price floor

The ₹50 price floor was the one M106 setting never varied (M50 swept the others). ₹25 / ₹100 both fail
(docs/research/m133.md): ₹25 1.492 vs 1.500 at offset 0, wins 5/10/15 but f2 1.717 vs 2.200; ₹100 costs 1-2.6 pts
CAGR. Robustness note for M106: the floor is not a knife edge. Variants: ~1,012.

## Session 2026-10-23 (cycles 10-15, M128-M133): summary

Six cycles: M128 downside-deviation score, M129 acceleration, M130 fill timing (information), M131 ERC weights, M132
trade-to-trade exit, M133 price floor. 0 of 5 candidates passed; variants ~1,012 (from ~1,005). M106 unchanged.
Lessons:
1. The month-end decision keeps flattering candidates (M129 1.625, M132 1.680, both fail other offsets). The bar's
   four-offset rule is doing its job; keep pre-screening at all four offsets first (`notebooks/prescreen.py REF CAND`).
2. Ranking (M127-M129) and weighting (M124, M127, M131) changes are exhausted on this book; so are buy filters
   (M120-M125) and regime variants (M122, M126, dispersion, illiquidity, weekly checks).
3. Realism: M106's open fill is worth ~0.4-0.5 pts CAGR a year over intraday fills; a day's delay ~0.6 (M130). Live:
   AMO orders into the pre-open, and watch for holdings moved to trade-to-trade (M132).
4. Robustness of M106: the ₹50 price floor (M133) and every other setting (M50, M109) sit on a plateau.
Each further price-only variant adds to the trial count and weakens any later "pass"; the next session should prefer
new data (shareholding history from 2015, MF flows from 2019 - both weak and short) or live work (M7), and should
start with the 2026-10-30 paper decision vs research.
New tools: `notebooks/prescreen.py`, `notebooks/m130_fill_timing.py`; engine-side options `RankingM128/M129`,
`PortfolioM131`, `ExitsM132` (all off by default in earlier configs; suite 315 passed, 9 skipped before M132).

## 2026-10-23, cycle 16: M134 promoter pledge events

Research: Indian pledging studies (BSE 500 2011-20 crash risk; Financial Management 2021, 1,452 firms; 2009-23
downside risk; NSE family firms 2009-19) all find pledging raises crash risk and lowers later returns. No study tests
it on momentum winners. NSE's current pledge snapshot API has no history, but the SAST Reg 31 event API
(`corporate-pledgedata-sast3132`) does, back to 2014. New: `mb data fetch pledges` (40,482 events 2014-2026-09 in
`data/raw/nse_pledges/`). Idea: skip buys, or also drop holdings, with a pledge creation or invocation in the last
180 days (8% of M106's 2015-23 buys). Result: fail at the pre-screen (docs/research/m134.md). pl180 scored 1.355 and
pl180h 1.416, vs 1.500. Both lose all four offsets and f2/f3, at −0.6 to −1.2 pts CAGR. Variants: ~1,014.
Pattern: governance and crash-risk screens (insider sells M111, deals M116, pledges M134) remove momentum winners that
then keep winning. Event-based filters on M106 have now failed four times.
Next queue: (1) after the 2026-10-30 close, compare the paper book's first decision with a research run; (2) live
prep (M7): flag pledge invocations and moves to trade-to-trade on held names in the daily ticket (information only, not
a rule change).

## 2026-10-23, cycle 17: ideas dropped at the information stage; live prep

Dropped before pre-registration (no backtest, not counted as variants):
- NSE ASM / short-term ASM lists: in Chari & Inamdar's NSE working paper, a 23% five-day run-up into inclusion reverses
  to about 0% after it. That is no drawdown signal, and the lists start in 2018.
- Bonus / split ex-dates: Indian announcement effects are +1.8% / +0.8% (Dhar & Chhaochharia), and no long-run drift
  study exists. Only 29 of M106's 1,271 buys came within 90 days after an ex-date, so the rule would hardly act.
- Dividend-payer screen: payer data is clean from 2010 (21% of M106's buys had no dividend in the prior two years,
  half of them in 2021-22). But Asem 2009 (JBF) finds the payer gap comes from losers, not winners.
Live prep (M7, the M132 note): `paper.off_series` lists held names whose newest row is outside `allowed_series`. They
appear in the daily log, the weekly ok and `mb paper status` (docs/paper.md). Research branch only; the running books
get it only if a later change is merged to m8. Smoke-run of `mb paper daily --no-fetch` here stops at "no daily
dataset" (expected on the research checkout); the new function is unit-tested.
Next queue: (1) after the 2026-10-30 evening job, compare the paper book's first decision with a research run of
`m120_ref` extended to that date. This needs a dataset through 2026-10-30 (`mb data build`) after fetching bhavcopy +
delivery. (2) Otherwise only new data families. Candidates left are weak: MF scheme holdings (monthly portfolios from
AMFI, 2019+ only), shareholding pattern (quarterly XBRL, heavy).
Queue note for M7 (implementation, not a signal): the fixed 25% gold sleeve could be held partly in Sovereign Gold
Bonds (2.5% a year interest; NSE series GB from about 2016) instead of GOLDBEES. That is worth up to +0.6 pts CAGR on
the sleeve, but SGBs trade at a moving premium or discount to gold, are thin, and new issues stopped in 2024. Only for
the fixed part (the risk-off switch trades too often). It needs the user's call; do not backtest it as a candidate.

## 2026-10-23, cycle 18: M135 paper support for decision offsets (tranches; live prep)

Research first (no new candidate; nothing counted): same-calendar-month seasonality (Heston & Sadka 2008) is mostly
absent in emerging markets (Li, Zhang & Zheng, 42 markets); no study of a small-cap index trend filter (and the
M95-M99 benchmark variants are done); Vijaykumar 2026 (SSRN 7394980, ten published momentum definitions on Indian
stocks) is behind a 403 here, and ranking changes are exhausted (M127-M129). Practitioner pages on stock-level MA exits
have no evidence (stops are a dead family).
Work (LOOP step 10, queued since cycle 8): the paper book now takes `schedule.decision_offset_sessions`, so M106 can
run as four quarter-capital tranches (offsets 0/5/10/15) without month-end luck (M117: tranche ~1.34 vs the 1.50 draw).
Changes: `targets(..., open_end=True)`, `calendar.sessions_left_in_month`, paper decides when N trading days are left
(calendar; data overrules once it reaches the next month), and the replay takes the open month's decision as the book
made it. Checks (docs/research/m135.md): 6 new tests, suite 332 passed / 9 skipped. `m135_m106_offN` trades are
byte-identical to `m120_ref_offN`. End to end on `nse_daily_delivery@2026-10-22` (read only), 2026-01..10-22: four
books, 0 replay mismatches, 8/8 decisions per book equal research. Equity gaps reach +1.34% at ₹2.5 lakh a tranche
(whole-share rounding; the alert limit is 2%).
Not deployed: drafts `configs/paper/momentum_m106_tranche_off{0,5,10,15}.yaml` (start 2026-11-02). The user decides
whether to run them beside or instead of M106. Deploying = merge to m8, pull in multibagger-v2, add one unit per book.
Variants: unchanged (~1,014).
Next queue: (1) after the 2026-10-30 evening job, compare the M106 paper book's first decision with research (needs a
dataset through 2026-10-30); (2) live prep: unit files for the tranche drafts (written, not installed) if the user says yes;
(3) new data families only for signals (MF holdings 2019+, shareholding pattern).

## 2026-10-23, cycle 19: M136 dataset refresh (data quality)

Fetched bhavcopy and delivery for 2026-09-29..10-22 and the 2026 corporate actions. Built `nse_research@2026-10-23`
(all checks pass). `m136_ref` (M106 on it, 2010-23) equals `m120_ref`: same 1,272 trades, same 1.500, equity within
float noise (docs/research/m136.md). Also this cycle: templated unit drafts `deploy/mb-paper-tranche@.service/.timer`
for the M135 tranche books (not installed). Variants: unchanged (~1,014).
Next queue: (1) after the 2026-10-30 evening job, fetch 10-23..10-30, build a dataset, and compare the M106 paper book's
first decision (`~/projects/multibagger-v2/data/paper/momentum_b_top25_gold25_jr_gap/days/2026-10-30.json`) with
`targets()` of `m136_ref` on that dataset; (2) the user's call on the tranche drafts.

## 2026-10-23, cycle 20: M137 offline Dhan order plan (live prep)

Research (journal only, nothing counted): MF crowding (only global studies, Indian evidence none), network /
supply-chain momentum (no emerging-market long-only evidence; China lead-lag fades at daily data), relative +
absolute momentum (IJoEM 2025; absolute momentum is dead here, M72), BacktestIndia "scaled turnover" (dropped in
cycle 10). Dropped at the information stage: risk-off share in GOLDBEES only while gold is above its 200-day average,
otherwise cash; it would act at 5 of 45 risk-off month-ends in 2010-23 (6 with a 12-month rule), too few to tell from
decision-day luck.
Work (LOOP step 10, M7): `mb live plan` turns the paper book's pending orders into Dhan v2 order bodies at the live
capital (sells MARKET in the pre-open, buys MARKET at the open, CNC, AMO) behind rails (order value, name weight,
GOLDBEES cap, buy total, order count, kill switch); `mb live reconcile` checks a saved Dhan holdings response
against the book; `mb data fetch dhan-scrips` stores Dhan's public scrip master. Nothing is sent and no token is read.
Checks (docs/research/m137.md): 13 new tests, suite 345 passed / 9 skipped; voladj 2026-09-30 decision maps 30/30
symbols and passes the rails; reconcile matches the current voladj book. Whole shares put a floor of ~₹2.5 lakh on live
capital for M106. Variants: unchanged (~1,014).
Next queue: (1) after the 2026-10-30 evening job: compare M106's first paper decision with research, and run
`mb live plan configs/live/dhan_m106.yaml --paper-root ~/projects/multibagger-v2` on its pending orders as the
first real dry run; (2) M7 needs the user: capital, client id, static IP; (3) signal ideas are thin; only new data
families are left.

## 2026-10-23, cycle 21: M138 moving-average distance in the rank

Idea (pre-registered by the previous session, runs made at code ba1d1b2; this session wrote the results): rank on a
blend of the vol-adjusted score and MAD = 21-day / 200-day SMA (Avramov, Kaplanski & Subrahmanyam 2021; MAD also times
92 country indices, Abudy, Kaplanski & Mugerman 2024 JIFMIM). Result: both fail the pre-screen (docs/research/m138.md):
mad50 1.484 vs 1.500 at offset 0, wins offsets 5/10/15 by 0.01-0.06 but loses f1/f2/f3; MAD alone 1.377, −0.3 to −1.3
pts CAGR everywhere. Variants: ~1,016.
Note: disk had 17 GB free at the start of this session (rule: ≥ 20 GB). The space is used by other projects, not this
one (runs/ 18 MB, datasets 1.1 GB); nothing deleted. Backtests write ~150 KB each, so research continued.
Dropped at the information stage: MAD (21/200) on JUNIORBEES in place of the 200-day filter (Abudy et al. 2024): the
regime-filter family is spent (M103 band, M122, M126 SMA ensembles), and smoothing the price is a third SMA variant.
Next queue: (1) after the 2026-10-30 evening job, compare M106's first paper decision with research and dry-run
`mb live plan`; (2) signal ideas are thin: new data families only.

## 2026-10-23, cycle 22: M139 short NIFTY futures instead of the gold switch

Research: no study tests a futures overlay on a long-only momentum book; the mechanism is portable alpha, and Daniel &
Moskowitz 2016 show past winners carry low beta after market falls (crash risk sits in losers). Idea: in risk-off keep
all picks and short NIFTY futures (0.375 / 0.75 of the book) instead of moving half the stocks to GOLDBEES. New:
`mb data fetch fo-bhav` (legacy F&O bhavcopy 2021-23 fetched; 2009-20 were already here) and strategy kind `hedged`.
Result: both fail the pre-screen (docs/research/m139.md): h375 1.376 / h75 1.413 vs 1.500, every offset lost; the
short lost ₹15 / ₹31 lakh over 45 risk-off months. Gold does two jobs in risk-off (less beta and a crisis asset);
the hedge does one. The risk-off instrument family (cash M88, gold M89, futures M139) is done. Variants: ~1,018.
Disk: free space fell to 9.7 GB during this cycle (other projects and ~/.cache grew; this repo added 0.4 GB of F&O
files). Below the 20 GB rule; nothing of other projects deleted. Next cycles should avoid new raw data until space is
freed (flagged in the ntfy line).
Next queue: (1) after the 2026-10-30 evening job, compare M106's first paper decision with research and dry-run
`mb live plan`; (2) no new raw data while disk < 20 GB; prefer analysis on data already here.

## 2026-10-23, cycle 23: M140 M106 at live capital sizes (realism, information)

Research first (journal only, nothing counted): Indian buybacks show no post-announcement drift (Agarwalla, Jacob &
Vasudevan, IIMA; Bhama 2023), dropped; Raju & Chandrasekaran's India long-only momentum paper is behind a 403; NSE
momentum-index rebalance flows (₹17,000 cr passive, June/December) are the dead "momentum index fund" family.
Work (LOOP step 10, M7 prep): `notebooks/m140_live_capital.py` replays M106 through `mb.live.paper.advance` (the
running books' code: whole shares, raw prices) over 2010-23 at five capitals (docs/research/m140.md). CAGR 29.11% at
₹2.5 lakh, 29.48% at ₹5 lakh, 29.66% at ₹10 lakh, 29.80% at ₹1 crore, vs 30.09% fractional; drawdown unchanged
(20.16%); DP fee on every sale day ≤ 0.03 pts. No book blocked in 14 years. For M7: ₹5 lakh or more.
Note: the paper code needs the dataset's fund list for pre-2011 data (no ISINs); live data is unaffected.
Each replay holds ~4 GB RAM for ~15 min: run one at a time, outside the paper-job windows.
Variants: unchanged (~1,018).
Next queue: (1) after the 2026-10-30 evening job, compare M106's first paper decision with research and dry-run
`mb live plan`; (2) M7 capital: the user's call, ≥ ₹5 lakh per M140; (3) disk below 20 GB: no new raw data.

## Session 2026-10-23 (cycles 21-23, M138-M140): summary

- M138 moving-average distance in the rank: fails (ranking family done: M127-M129, M138).
- M139 short NIFTY futures instead of the gold switch: fails at every offset (risk-off instrument family done: cash
  M88, gold M89, futures M139). New tools kept: `mb data fetch fo-bhav` (F&O bhavcopy now 2009-2023), strategy kind
  `hedged`.
- M140 live capital (information): the paper engine reproduces M106 over 2010-23 within 0.3-1.0 pts CAGR from ₹1 crore
  down to ₹2.5 lakh; ≥ ₹5 lakh recommended for M7.
- Dropped at the information stage (not counted): MAD on JUNIORBEES, buybacks, momentum-index rebalance flows,
  re-running the deflated Sharpe (nothing adopted since M104, so M106's evidence is unchanged).
Variants ~1,018. M106 unchanged; running paper books untouched.
State for the next session: signal ideas that need only data on this box are spent; each new price-only variant adds
to the trial count. The paper job's daily replay already compares each decision with research, so the 2026-10-30
check is mostly automatic: read `replays/` and the 10-30 day record, then dry-run `mb live plan`. Disk is at 8.7 GB
free (other projects and ~/.cache grow); fetch no new raw data until it is back above 20 GB. Each M140-style replay
holds ~4 GB RAM for ~15 min.

## 2026-10-24/25, cycle 24: M141 quarterly results (new data family)

Research: Novy-Marx 2015 (earnings momentum subsumes price momentum, US), Chan, Jegadeesh & Lakonishok 1996, Indian SUE
drift (Harshita, Singh & Yadav 2018; against: Gupta & Dhusia 2021), NSE's Smallcap250 Momentum Quality 100 index (screens
momentum names on ROE, leverage, EPS-growth variability). Dropped at the information stage: single-stock futures basis
as a shorting-demand signal (M106 buys almost no F&O names, M118/M119).
New data: NSE quarterly results for every symbol M106 could buy (2,649 symbols, 93,701 standalone filings, 2007-24,
old HTML pages + XBRL; `mb data fetch results`, `src/mb/sources/nse_results.py`, 557 MB in `data/raw/nse_results`).
Net profit parses for ≥ 98.7% of filings each year. The fetch took ~6 h with four workers; NSE refused one burst of
~60 symbols, recovered by a single fill-in pass.
Idea: no new buys of loss-makers (TTM) or of names whose latest quarterly profit fell year on year (19% of buys).
Result: both fail the pre-screen (docs/research/m141.md): loss 1.394, yoy 1.408 vs 1.500; yoy wins offsets 10 and 15
(1.312 / 1.501) on smaller drawdowns but loses 0 and 5, every fold, and CAGR everywhere. Variants: ~1,020.
Pattern: every buy filter, now including fundamentals, trades CAGR for drawdown inside the decision-day band.
Next queue: (1) after the 2026-10-30 evening job, compare M106's first paper decision with research and dry-run
`mb live plan`; (2) with fundamentals now on disk: an earnings-stability or valuation (E/P cap) screen is the same
buy-filter family, so only one more try, and only with a stronger reason than M141's; (3) the M113 pullback blend
(dev 1.876, locked 1.533 vs 1.314) is the largest effect seen and fails only f2; it needs a paper-engine pullback sleeve
and the user's call, not more fitting.

## 2026-10-25, cycle 25: M142 the m108-line pullback blend through the loop bar (information)

Why: the biggest effect found anywhere (M113 on branch m108: M106 0.8 + 5-name RSI(2) pullback 0.2, monthly
rebalanced; dev 1.876, locked 2024-26 1.533 vs 1.314) had never faced this loop's bar. Code cherry-picked from m108
(pullback, calendar, rebalanced blend, engine limit entries; docs left out, their milestone numbers clash).
Result (docs/research/m142.md): wins offset 0 and offsets 5/10/15 (1.876 / 1.244 / 1.445 / 1.660 vs 1.500 / 1.080 /
1.273 / 1.409), after tax (1.412 vs 1.102), 25 bps (1.679 vs 1.411), neighbours (w10 1.726, w30 1.832). Fails f2
(2014-17) at every offset, at 25 bps and after tax, and the bootstrap is 74.8% (bar 85%). Not adopted.
Correction found while writing: M106's worst drawdown is 2022-05-25 (20.1%), not March 2020; the old summary line
in calmar-search.md ("max DD of every long-only book is March 2020") predates the Next 50 filter. A's worst is
2020-03-23 (15.6%). Variants: ~1,027.
For the user: this is the one config that beats M106 on whole-period Calmar in dev, out of sample, after tax and at
costs; its weakness is a steady bull market (f2). Paper trading it needs a daily pullback sleeve in the paper engine
(not built) and the user's OK.
Next queue: (1) 2026-10-30: M106's first paper decision vs research, dry-run `mb live plan`; (2) if the user wants
the blend on paper: build paper support for the pullback sleeve (research branch only, unit drafted, not installed);
(3) fix the calmar-search summary line about March 2020.

## 2026-10-25, cycle 26: M143 scaled turnover

Idea dropped in cycle 10 for lack of share counts; M141's results data now gives them (paid-up / face value, 97% of
filings). Rule: no new buys in the top 20% / 40% of 50-day traded value / market cap (Lee & Swaminathan 2000;
BacktestIndia 2026). Result (docs/research/m143.md): both lose every offset and fold at -3 to -6 pts CAGR (tr20 1.477,
tr40 1.420 vs 1.500). The heavily traded winners are M106's best names. Variants: ~1,029.
New tool: `mb.data.fundamentals.turnover_ratio` (market cap carried through splits by adj_factor).
Next queue: (1) 2026-10-30 paper decision check and `mb live plan` dry run; (2) market cap now exists: a size tilt is
the only fundamentals idea left that is not a buy filter; but M33/M66 (lower ADV floors) already push towards smaller
names, and Indian momentum is reported stronger in large caps (NSE RP 2012), so expected weak; (3) the M142 blend's
paper support if the user asks.

## 2026-10-25, cycle 27: M144 value sleeve

Idea: the only structural gain so far is a diversifying sleeve (M142); value is the textbook partner of momentum
(Asness, Moskowitz & Pedersen 2013). New strategy kind `value` (top 25 by trailing four-quarter earnings / market cap,
NSE results from M141). The first try was stopped by the data gate on MANDHANA (2016-09-22 demerger, no factor in
the feed); override added, dataset `nse_research@2026-10-25` built (unexplained jumps 994 → 993; M106 unchanged on it).
Result (docs/research/m144.md): the value book alone has a 75.7% drawdown in 2010-13 (real value-trap collapses),
Calmar 0.168; blends v20 1.165 / v30 0.944 vs 1.500, every offset and 25 bps lost. Variants: ~1,031.
Lesson: on NSE small caps a price-only signal (M106) already avoids the junk that cheap-valuation screens buy.
Next queue: (1) 2026-10-30 paper decision check and `mb live plan` dry run (use `nse_research@2026-10-25` or newer);
(2) if another sleeve is tried, it must be something that did well in 2011-13 and in 2022, when M106 drew down;
gold already covers that, so expected weak; (3) the M142 blend's paper support if the user asks.

## 2026-10-25, cycle 28: M145 quality-screened value sleeve

Follow-up to M144 with its own reason (value traps; Piotroski 2000, Novy-Marx 2013, QMJ). Screen: positive profit in
each of the last four quarters and trailing profit growth. Result (docs/research/m145.md): the book gains 3 pts CAGR
(15.7%) but keeps its 75% 2010-13 drawdown; blends q20 1.197 / q30 0.862 vs 1.500, every offset and 25 bps lost.
Value family closed. Variants: ~1,033.
Dropped at the information stage this cycle (not counted): deflated Sharpe of the M142 blend (the test scores mean
return; the blend's edge is drawdown, so it cannot answer the question); NSE shareholding patterns (API history
starts 2021, no delisted names).
Scheduled: a reminder fires 2026-10-30 18:45 UTC for the first M106 paper decision check (send_later, trigger
trig_016C6ZdixxLfubtN7wtQGu6Y).

## 2026-10-25, cycle 29: M146 corporate-action audit (data quality)

46 unexplained jumps sat on feed demerger / scheme / rights / split rows with no factor (`notebooks/m146_ca_audit.py`).
Added 39 overrides (exact factors from feed text for 2005-07 splits/bonuses, TERP for rights with known issue price,
ex-date price discovery for demergers and unknown rights); skipped CENTEXT 2005 and penny-stock AGM price flips.
Dataset `nse_research@2026-10-25b`: unexplained jumps 993 → 957, checks pass. M106 on it: 1.490 vs 1.500 (ANANTRAJ's
2020 demerger now ranks it in 2021); offsets 5/10/15 within 0.004. Use 2026-10-25b and `m146_ref*` from now on.
Found: m8's BHAGYANGR override (ad31abf) was never in research; now it is (same factor). No paper book holds any newly
fixed name. Variants: unchanged (~1,033; references, not candidates).
Next queue: (1) 2026-10-30 paper decision check (scheduled); (2) the M142 blend's paper support if the user asks;
(3) the remaining ~950 unexplained jumps are mostly real moves or have no feed row; a second audit pass would need
another source (BSE corporate actions), not worth it unless a book trips the gate.
