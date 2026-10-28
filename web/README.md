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

## Published site

multibagger.rohanahire.com serves a built copy from `/var/www/multibagger.rohanahire.com` on the VPS. A full export
needs the run records and datasets, so it is made on the Mac and copied there (`npm run build`, then rsync `dist/`).
The paper books change every evening, so `deploy/mb-dashboard-refresh.*` runs `mb dashboard refresh-paper` on the VPS
after the paper jobs: it rewrites only the books' live state in the published `bundle.json`. A new full export
overwrites the live state until that night's refresh.
