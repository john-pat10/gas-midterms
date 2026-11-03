# Do High Gas Prices Sink the President's Party?

An empirical test of a common political claim: that rising gas prices cost the
president's party in U.S. midterm elections. The project uses 46 years of
public data (12 midterms, 1978–2022) at both the national and state level.

**Answer: not reliably.** Gas prices explain about 3% of the variation in midterm
House swing. Presidential approval explains about 36%. In the state panel, comparing
states *within the same election*, states with larger gas spikes did not swing
harder against the president.

![timeline](reports/figures/timeline.png)

## Findings

| | Result |
|---|---|
| Gas price change vs. swing (national, n = 12) | r = 0.16, slope not significant (p = 0.38) |
| Presidential approval vs. swing | r = 0.60, the strongest single predictor |
| Gas → approval | 10% real gas rise ≈ −1.5 approval points (p ≈ 0.09) |
| Gas, holding approval fixed | slightly *positive*, but driven by 2022 (p = 0.32 without it) |
| State panel, year fixed effects | no gas penalty in any specification |

The positive coefficient after controlling for approval is most likely a
**bad-control artifact**. If gas prices hurt the president *through* approval,
controlling for approval removes that channel, and the leftover gas coefficient
picks up whatever else happened in high-gas years. 2022, for example, had both
a gas spike and the *Dobbs* ruling.

Full regression tables: [`reports/results.md`](reports/results.md)

## Interactive dashboard

`dashboard/index.html` is a single self-contained file. Open it in a browser, or
host it on GitHub Pages. It includes:
- a national scatter where you choose the comparison variable (gas, approval, inflation and more)
- a state tile map and a within-year scatter for each midterm
- a coefficient plot comparing every model's gas estimate with 95% confidence intervals

## How it works

```
src/fetch_data.py       download raw data (EIA, BLS, BEA, MIT Election Lab)
src/build_dataset.py    clean + merge -> data/processed/{national,state_panel}.csv
src/analysis.py         regressions, figures, reports/results.md
src/build_dashboard.py  bake results into dashboard/index.html
notebooks/analysis.ipynb  step-by-step walkthrough of the analysis
```

### Run it

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run_all.py
```

One manual step: the MIT House file sits behind a Harvard Dataverse sign-in form.
Download `1976-2024-house.tab` from https://doi.org/10.7910/DVN/IG0UN2 into
`data/raw/`. The script tells you if it's missing.

## Data

| Variable | Source | Level |
|---|---|---|
| House election results | MIT Election Data + Science Lab, 1976–2024 | district |
| Retail gasoline price (monthly) | EIA Monthly Energy Review, Table 9.4 | national |
| Motor gasoline price (annual) | EIA State Energy Data System (SEDS) | state |
| Crude oil cost | EIA Monthly Energy Review, Table 9.1 | national |
| CPI-U, unemployment rate | BLS public API | national / state |
| Per-capita personal income | BEA SAINC1 | state |
| Presidential approval | Gallup, last pre-midterm reading (hand-entered in `data/manual/`) | national |

## Method

- **Outcome ("swing"):** change in the president's party's share of the two-party
  House vote, midterm year vs. the presidential year two years earlier. Only
  districts with both a Democrat and a Republican on the ballot count, so unopposed races don't distort the share.
- **Gas price change:** % change in the real (2024-dollar) gas price over the same two-year window.
- **National models:** OLS with robust (HC1) standard errors, adding one control at a time
  because n = 12. Includes a leave-one-out sensitivity check.
- **State panel (584 state-midterms):** weighted by number of districts. Pooled models
  cluster SEs by year. Fixed-effects models (year, and year + state) cluster by state.
  Robustness checks keep only mostly-contested states and drop 2022.

## Limitations

- Only 12 midterms, so national estimates are imprecise.
- SEDS state gas prices are annual averages and include Nov–Dec, after the election.
- Gas prices move mostly together nationwide, so within-year state variation is small.
- House vote totals mix in incumbency and redistricting effects. Seat counts computed
  from the data differ from official tallies by 1–2 seats in some years.
- Gallup approval values are hand-entered. Verify them against Gallup before citing.

## Ideas for extending it

- Forecast the 2026 midterm out of sample (as of Nov 2, 2026, the election is tomorrow).
- Add presidential-year elections as a placebo test.
- Use county-level commuting data (miles driven) to test whether gas hits car-dependent areas harder.
- Use a formal mediation analysis (gas → approval → swing).
