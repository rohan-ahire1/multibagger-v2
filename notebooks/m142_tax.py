"""M142 (docs/research/m142.md): before- and after-tax Calmar of monthly-rebalanced blends, whole period and folds.

Each sleeve is taxed as its own book (M110 model, configs/tax/india_fy2026.yaml): momentum sleeves from the simulator's
fills, other sleeves (pullback) from their trades turned into buy / sell fills. The after-tax sleeve curves are mixed
with the blend's monthly rule and costs (`mix_rebalanced`'s loop, equity only). Gains realised by month-end moves
between sleeves are not taxed. The pre-tax mix is checked against the blend run's record.

Usage: uv run python notebooks/m142_tax.py BLEND_CONFIG@RUN_ID ... | MOMENTUM_CONFIG@RUN_ID ...
"""
import sys
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.evaluation.metrics import equity_metrics
from mb.evaluation.tax import after_tax, realised
from mb.strategy.blend.run import load_sleeves
from mb.strategy.momentum.run import simulate
from mb.strategy.registry import runner

ROOT = Path('.')
TAX = load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml')


def trades_to_fills(t: pl.DataFrame) -> pl.DataFrame:
    """A closed signal-engine trade -> a buy on entry (cash_flow -shares x entry_price) and a sell on exit (the buy's
    cost plus the trade's pnl, so the taxed gain is the pnl net of costs)."""
    t = t.filter(pl.col('exit_date').is_not_null()).with_columns((pl.col('shares') * pl.col('entry_price')).alias('cost'))
    buys = t.select(pl.col('entry_date').alias('date'), 'symbol', pl.lit('buy').alias('side'), 'shares',
                    (-pl.col('cost')).alias('cash_flow'))
    sells = t.select(pl.col('exit_date').alias('date'), 'symbol', pl.lit('sell').alias('side'), 'shares',
                     (pl.col('cost') + pl.col('pnl')).alias('cash_flow'))
    return pl.concat([buys, sells]).sort('date', pl.col('side') == 'sell')


def sleeve_curves(sc) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(pre-tax equity, after-tax equity) of one sleeve config, both with columns date, equity."""
    if sc.strategy.name == 'momentum':
        res = simulate(sc, ROOT)
        eq, fills = res.equity.select('date', 'equity'), res.fills
    else:
        r = runner(sc.strategy.name)(sc, ROOT)
        eq, fills = r.equity.select('date', 'equity'), trades_to_fills(r.trades)
    gains, _ = realised(fills, TAX)
    post = after_tax(eq, gains, TAX).select('date', pl.col('after').alias('equity'))
    return eq, post


def mix(curves: list[pl.DataFrame], w: list[float], market, capital: float) -> tuple[pl.DataFrame, float]:
    """Monthly-rebalanced mix of equity curves (the blend runner's rule and cost); returns curve and turnover x."""
    dates = curves[0]['date'].to_list()
    eq = [c['equity'].to_list() for c in curves]
    slip = market.slippage_bps_per_side / 10_000.0
    rt = (1.0 - (1.0 - slip) * (1.0 - market.sell_charge_rate)) + ((1.0 + slip) * (1.0 + market.buy_charge_rate) - 1.0)
    hold = [x * capital for x in w]
    out, moved_total = [], 0.0
    for t in range(len(dates)):
        if t > 0:
            hold = [h * eq[i][t] / eq[i][t - 1] for i, h in enumerate(hold)]
        out.append(sum(hold))
        if t + 1 < len(dates) and dates[t + 1].month != dates[t].month:
            total = sum(hold)
            moved = sum(max(0.0, wi * total - h) for wi, h in zip(w, hold, strict=True))
            moved_total += moved / total
            hold = [wi * (total - moved * rt) for wi in w]
    return pl.DataFrame({'date': dates, 'equity': out}), moved_total


def row(label, e, a, b) -> str:
    m = equity_metrics(e, a, b)
    return f"{label:10s} {m['calmar']:.3f} ({m['cagr_pct']:.2f}% / {m['max_dd_pct']:.2f}%)"


for arg in sys.argv[1:]:
    path, _, rid = arg.partition('@')
    cfg = load_strategy_config(Path(path), ROOT)
    if cfg.strategy.name == 'blend':
        parts = [(w, sleeve_curves(sc)) for w, sc in load_sleeves(cfg, ROOT)]
        w = [x for x, _ in parts]
        pre, _ = mix([c[0] for _, c in parts], w, cfg.market, cfg.params.initial_capital)
        post, turn = mix([c[1] for _, c in parts], w, cfg.market, cfg.params.initial_capital)
        yrs = (pre['date'][-1] - pre['date'][0]).days / 365.25
        note = f'  month-end moves between sleeves: {turn / yrs:.2f}x the book a year (untaxed here)'
    else:
        pre, post = sleeve_curves(cfg)
        note = ''
    if rid:
        rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
        k = rec['equity'][0] / pre['equity'][0]
        diff = (pre.join(rec, on='date', suffix='_rec')
                .select((pl.col('equity') * k / pl.col('equity_rec') - 1).abs().max()).item())
        print(f"{cfg.strategy.version}: pre-tax mix vs run {rid}: max |ratio - 1| = {diff:.2e}{note}")
    a, b = cfg.strategy.period.start, cfg.strategy.period.end
    print('  ' + row('pre whole', pre, a, b) + '   ' + row('post whole', post, a, b))
    for f in cfg.baselines.folds:
        print('  ' + row(f'pre {f.name[:2]}', pre, f.start, f.end) + '   ' + row(f'post {f.name[:2]}', post, f.start, f.end))
