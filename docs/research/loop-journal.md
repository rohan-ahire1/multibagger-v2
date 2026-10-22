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
