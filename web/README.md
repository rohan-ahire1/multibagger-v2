# Research dashboard

A local, static dashboard for the run records. It reads one JSON file, `public/bundle.json`, made by the exporter. Nothing is computed by a server.

Make the bundle (from the repo root):

```
uv run mb dashboard export configs/dashboard/research.yaml [--data-root DIR]
```

`--data-root` (or `MB_DATA_ROOT`) is the folder that holds `runs/` and `data/`. It defaults to the repo root. Which runs and paper books appear is set in `configs/dashboard/research.yaml`.

Run the app (from `web/`):

```
npm install
npm run dev                          # development
npm run build && npm run preview     # built copy
```

Views: Overview, Trades, Metrics, Monthly, Compare, Paper. Pick a run from the top right and compare up to 3. The date range re-slices the recorded equity; it does not re-run the backtest. Every page header shows the config file and run id. Theme (light or dark) is remembered in the browser.

Re-export after new runs or paper days, then reload the page.
