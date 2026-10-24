# Personal Investor

An interactive planner for Canadian investors (all amounts in CAD): enter an amount and a risk level (1–5) to see

- a Monte Carlo projection of possible outcomes over time (10th–90th percentile bands),
- the suggested asset mix (cash, bonds, index ETFs, individual stocks, REITs, gold) as an editable table and donut chart,
- your holdings with **live prices in CAD** — add TSX or US stocks/ETFs or crypto by share count; each holding automatically fills
  its asset class's slice of the mix, split by market value (e.g. stocks at 10% + 1 share of AAPL = AAPL is 10%),
- example ideas for the chosen risk level — mostly TSX-listed funds and companies (XEQT, VGRO, ZAG, RY, SHOP…), plus crypto,
- bond and GIC examples (GICs, Government of Canada T-bills and bonds, provincial, real return and corporate bonds, bond ETFs)
  with live Bank of Canada yields and links to Canadian brokerages.

## Live data sources (free, no API key)

| Data | Source |
| --- | --- |
| TSX stocks & ETFs | TMX Money (CAD) |
| US stocks & ETFs | Nasdaq quote API (USD, may be delayed ~15 min), converted to CAD |
| USD/CAD rate | Coinbase live rate (every minute), falling back to the Bank of Canada daily rate |
| Crypto | CoinGecko (CAD) |
| Government of Canada yields | Bank of Canada Valet API |

Prices are fetched by the local Python server (`/api/quotes`, `/api/yields`) and cached for 60 seconds,
so opening the HTML file directly won't show live prices — run it with `uv run`.

## Run

```bash
uv run personal-investor
```

Options: `--port 8080`, `--no-browser`. The page lives at `src/personal_investor/static/index.html`
and the live-data API is in `src/personal_investor/quotes.py`.

## Working with uv

The project is managed with [uv](https://docs.astral.sh/uv/). Dependencies live in `pyproject.toml` and are pinned in `uv.lock`;
`.python-version` selects Python 3.14, which uv downloads if it isn't installed.

```bash
uv sync                  # create .venv and install locked dependencies
uv run personal-investor # run the app (syncs automatically first)
uv add <package>         # add a dependency (updates pyproject.toml and uv.lock)
uv remove <package>      # remove a dependency
uv lock --upgrade        # upgrade locked versions
uv build                 # build sdist/wheel with the uv_build backend
```

Install uv with `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

Educational tool only — not financial advice.
