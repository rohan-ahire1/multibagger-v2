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
