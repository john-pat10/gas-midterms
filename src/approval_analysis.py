"""Do gas prices move presidential approval? Monthly analysis, Feb 1977 - Dec 2024.

The midterm analysis has only 12 data points. Here we use about 570 months of
Gallup approval polls (Carter through Biden) to estimate the gas -> approval link,
then combine it with the approval -> midterm swing link to get the *total* effect
of gas prices on midterms (a mediation analysis).

Models
------
L1  approval level ~ log real gas + president fixed effects
L2  + unemployment, inflation, time in office, rally events
L3  + a separate time trend for each president (guards against coincidental trends)
D   month-to-month change in approval ~ gas changes this month and 1-12 months earlier
    (a "distributed lag": how long does a gas shock take to show up?)
P   L2 run separately for the president's own party, independents, and the opposition

Outputs: reports/approval_gas.md, reports/figures/approval_*.png, dashboard/approval.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).parent))
from build_dataset import RAW, load_approval_polls, load_cpi, load_mer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
FIG = REPORTS / "figures"
DASH = ROOT / "dashboard"

END = pd.Period("2024-12", "M")  # macro controls in this project end in 2024
LAGS = 12
HAC = {"cov_type": "HAC", "cov_kwds": {"maxlags": 12}}
TEN_PCT = np.log(1.10)

PARTY = {"Carter": "D", "Reagan": "R", "G.H.W. Bush": "R", "Clinton": "D", "G.W. Bush": "R",
         "Obama": "D", "Trump 1": "R", "Biden": "D"}

# Rally-round-the-flag and crisis months that move approval for reasons unrelated
# to the economy. Approximate windows.
EVENTS = {
    "rally_iran": ("1979-11", "1980-01"),   # hostage crisis
    "rally_gulf": ("1991-01", "1991-03"),   # Gulf War
    "rally_911": ("2001-09", "2002-01"),    # September 11
    "rally_iraq": ("2003-03", "2003-04"),   # Iraq invasion
}


def build_monthly() -> pd.DataFrame:
    polls = load_approval_polls()
    polls = polls[(polls["source"] == "gallup") & polls["president"].isin(PARTY)]
    polls["month"] = polls["end"].dt.to_period("M")
    m = polls.groupby(["president", "month"])[["approve", "dem", "ind", "rep"]].mean()

    frames = []
    for p, g in m.groupby(level=0):
        g = g.droplevel(0)
        full = pd.period_range(g.index.min(), min(g.index.max(), END), freq="M")
        g = g.reindex(full)
        missing = g["approve"].isna()
        g = g.interpolate(limit=2, limit_area="inside")  # fill gaps of up to 2 months
        g["interpolated"] = missing & g["approve"].notna()
        g["president"] = p
        g["tenure"] = np.arange(1, len(g) + 1)
        frames.append(g)
    df = pd.concat(frames).rename_axis("month").reset_index()
    # Inauguration months contain polls for two presidents: keep the incoming one.
    df = df.sort_values(["month", "tenure"]).drop_duplicates("month", keep="first")
    df = df.sort_values("month").reset_index(drop=True)

    cpi = load_cpi()
    cpi["month"] = pd.PeriodIndex(pd.to_datetime(cpi[["year", "month"]].assign(day=1)), freq="M")
    cpi = cpi.set_index("month")["cpi"]
    gas = load_mer("mer_retail_gasoline.csv", "RUUCUUS")
    gas.index = pd.PeriodIndex([pd.Period(year=y, month=mo, freq="M") for y, mo in gas.index])
    bls = pd.read_csv(RAW / "bls_series.csv")
    ur = bls[bls["series_id"].str.startswith("LASST")].groupby(["year", "month"])["value"].mean()
    ur.index = pd.PeriodIndex([pd.Period(year=y, month=mo, freq="M") for y, mo in ur.index])

    macro = pd.DataFrame({"gas": gas, "cpi": cpi, "unemp": ur}).sort_index()
    macro["real_gas"] = macro["gas"] / macro["cpi"] * macro.loc[END, "cpi"]
    macro["log_gas"] = np.log(macro["real_gas"])
    macro["inflation"] = 100 * (macro["cpi"] / macro["cpi"].shift(12) - 1)
    macro["dlog_gas"] = macro["log_gas"].diff()
    for k in range(1, LAGS + 1):
        macro[f"dlog_gas_l{k}"] = macro["dlog_gas"].shift(k)
    macro["d_unemp"] = macro["unemp"].diff()
    macro["d_infl"] = macro["inflation"].diff()

    df = df.join(macro, on="month")
    df["pres_party"] = df["president"].map(PARTY)
    df["own"] = np.where(df["pres_party"] == "D", df["dem"], df["rep"])
    df["opp"] = np.where(df["pres_party"] == "D", df["rep"], df["dem"])
    df["log_tenure"] = np.log(df["tenure"])
    df["d_approve"] = df.groupby("president")["approve"].diff()
    for name, (a, b) in EVENTS.items():
        df[name] = df["month"].between(pd.Period(a, "M"), pd.Period(b, "M")).astype(int)
    df["d_rally"] = df[list(EVENTS)].sum(axis=1).diff().fillna(0)
    return df[df["month"] <= END]


def effect(model, var, scale=TEN_PCT) -> dict:
    b, se = model.params[var], model.bse[var]
    return {"b": float(b * scale), "se": float(se * scale), "p": float(model.pvalues[var])}


def cumulative(model, names: list[str]) -> dict:
    """Sum of lag coefficients (total effect of a permanent 10% gas rise), with its SE."""
    r = np.zeros(len(model.params))
    for n in names:
        r[list(model.params.index).index(n)] = 1
    t = model.t_test(r)
    return {"b": float(t.effect[0] * TEN_PCT), "se": float(t.sd[0][0] * TEN_PCT), "p": float(t.pvalue)}


def main() -> None:
    df = build_monthly()
    df.to_csv(PROC / "monthly_approval.csv", index=False)
    events = " + ".join(EVENTS)
    controls = "unemp + inflation + log_tenure + " + events

    lv = df.dropna(subset=["approve", "log_gas", "unemp", "inflation"])
    models = {
        "L1": smf.ols("approve ~ log_gas + C(president)", lv).fit(**HAC),
        "L2": smf.ols(f"approve ~ log_gas + {controls} + C(president)", lv).fit(**HAC),
        "L3": smf.ols(f"approve ~ log_gas + {controls} + C(president) + C(president):tenure", lv).fit(**HAC),
    }
    lag_names = ["dlog_gas"] + [f"dlog_gas_l{k}" for k in range(1, LAGS + 1)]
    ch = df.dropna(subset=["d_approve", "d_unemp", "d_infl"] + lag_names)
    dmodel = smf.ols(f"d_approve ~ {' + '.join(lag_names)} + d_unemp + d_infl + d_rally + C(president)", ch).fit(**HAC)

    # Impulse response: cumulative effect after k months of a permanent 10% rise
    irf = [{"month": k, **cumulative(dmodel, lag_names[: k + 1])} for k in range(LAGS + 1)]

    party = {}
    for grp in ["own", "ind", "opp"]:
        sub = df.dropna(subset=[grp, "log_gas", "unemp", "inflation"])
        party[grp] = effect(smf.ols(f"{grp} ~ log_gas + {controls} + C(president)", sub).fit(**HAC), "log_gas")
        party[grp]["n"] = len(sub)

    # Unemployment and inflation effects from L2, for comparison
    other = {
        "unemp_1pt": {"b": float(models["L2"].params["unemp"]), "se": float(models["L2"].bse["unemp"]),
                      "p": float(models["L2"].pvalues["unemp"])},
        "inflation_1pt": {"b": float(models["L2"].params["inflation"]), "se": float(models["L2"].bse["inflation"]),
                          "p": float(models["L2"].pvalues["inflation"])},
    }

    # ---- Mediation: gas -> approval -> midterm swing ----
    nat = pd.read_csv(PROC / "national.csv")
    sm = smf.ols("swing ~ gas_chg_2y + approval", nat).fit(cov_type="HC1")
    a, se_a = models["L2"].params["log_gas"], models["L2"].bse["log_gas"]   # approval pts per 1.0 log gas
    bA, se_b = sm.params["approval"], sm.bse["approval"]                     # swing pts per approval pt
    g = np.log(1.20)                                                         # a 20% real rise
    indirect = a * g * bA
    se_ind = g * np.sqrt(bA**2 * se_a**2 + a**2 * se_b**2)                  # Sobel / delta method
    direct, se_dir = sm.params["gas_chg_2y"] * 20, sm.bse["gas_chg_2y"] * 20
    mediation = {
        "approval_per_20pct": float(a * g), "approval_per_20pct_se": float(g * se_a),
        "swing_per_approval_pt": float(bA),
        "indirect": float(indirect), "indirect_se": float(se_ind),
        "direct": float(direct), "direct_se": float(se_dir),
        "total": float(indirect + direct), "total_se": float(np.sqrt(se_ind**2 + se_dir**2)),
    }

    res = {
        "n_months": int(len(lv)), "start": str(lv["month"].min()), "end": str(lv["month"].max()),
        "levels": {k: {**effect(m, "log_gas"), "r2": float(m.rsquared), "n": int(m.nobs)} for k, m in models.items()},
        "changes_cumulative_12m": irf[-1], "changes_n": int(dmodel.nobs),
        "irf": irf, "party": party, "other": other, "mediation": mediation,
        "interpolated_share": float(df["interpolated"].mean()),
    }
    write_report(res)
    figures(df, irf)
    series = df[["month", "president", "pres_party", "approve", "real_gas", "unemp", "inflation"]].copy()
    series["month"] = series["month"].astype(str)
    (DASH / "approval.json").write_text(json.dumps({
        "results": res,
        "series": series.round(2).replace({np.nan: None}).to_dict(orient="records"),
    }), encoding="utf-8")
    print(open(REPORTS / "approval_gas.md", encoding="utf-8").read().encode("ascii", "replace").decode())


def write_report(r: dict) -> None:
    L = r["levels"]
    def f(e, unit="pts"):
        return f"{e['b']:+.2f} {unit} (SE {e['se']:.2f}, p = {e['p']:.3f})"
    m = r["mediation"]
    md = f"""# Gas prices and presidential approval (monthly, {r['start']} to {r['end']})

{r['n_months']} months of Gallup approval (Carter through Biden), monthly average of polls.
Gaps of up to two months are filled by linear interpolation ({r['interpolated_share']:.0%} of months).
Effects are scaled to **a 10% rise in the real (inflation-adjusted) price of gasoline**.
Standard errors are Newey-West (HAC, 12 lags) to allow for autocorrelation.

## 1. Does approval fall when gas prices rise?

| Model | Effect of a 10% real gas rise on approval | R² |
|---|---|---|
| L1: president fixed effects only | {f(L['L1'])} | {L['L1']['r2']:.2f} |
| L2: + unemployment, inflation, time in office, rally events | {f(L['L2'])} | {L['L2']['r2']:.2f} |
| L3: + each president's own time trend | {f(L['L3'])} | {L['L3']['r2']:.2f} |
| D: month-to-month changes, 12 lags (cumulative) | {f(r['changes_cumulative_12m'])} | |

For comparison, in L2 one extra point of unemployment moves approval
{r['other']['unemp_1pt']['b']:+.2f} pts (p = {r['other']['unemp_1pt']['p']:.3f}), and one extra point of
inflation moves it {r['other']['inflation_1pt']['b']:+.2f} pts (p = {r['other']['inflation_1pt']['p']:.3f}).

## 2. How fast? (cumulative effect of a lasting 10% rise, model D)

| Months after the rise | 0 | 1 | 3 | 6 | 9 | 12 |
|---|---|---|---|---|---|---|
| Approval change (pts) | {' | '.join(f"{r['irf'][k]['b']:+.2f}" for k in [0, 1, 3, 6, 9, 12])} |

## 3. Who reacts? (model L2 by party of respondent)

| Group | Effect of a 10% real gas rise |
|---|---|
| President's own party | {f(r['party']['own'])} |
| Independents | {f(r['party']['ind'])} |
| Opposition party | {f(r['party']['opp'])} |

## 4. Putting it together: gas → approval → midterm swing

For a 20% real gas rise over the two years before a midterm:

| Path | Effect on president's party swing |
|---|---|
| Gas → approval | {m['approval_per_20pct']:+.2f} approval pts (SE {m['approval_per_20pct_se']:.2f}) |
| × approval → swing | {m['swing_per_approval_pt']:+.3f} swing pts per approval pt |
| **Indirect (through approval)** | **{m['indirect']:+.2f} pts** (SE {m['indirect_se']:.2f}) |
| Direct (gas, holding approval fixed) | {m['direct']:+.2f} pts (SE {m['direct_se']:.2f}) |
| **Total** | **{m['total']:+.2f} pts** (SE {m['total_se']:.2f}) |

The indirect path uses model L2 (monthly, ~570 obs). The approval → swing and direct
coefficients come from the 12-midterm national regression, so they are much less precise.
Indirect-effect SE uses the delta method (Sobel).
"""
    (REPORTS / "approval_gas.md").write_text(md, encoding="utf-8")


def figures(df: pd.DataFrame, irf: list[dict]) -> None:
    plt.rcParams.update({"figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    fig, ax = plt.subplots(figsize=(7, 4))
    ks = [x["month"] for x in irf]
    b = np.array([x["b"] for x in irf]); se = np.array([x["se"] for x in irf])
    ax.fill_between(ks, b - 1.96 * se, b + 1.96 * se, color="#b86e0a", alpha=0.18, lw=0)
    ax.plot(ks, b, color="#b86e0a", lw=2, marker="o", ms=4)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("Months after a lasting 10% real gas price rise")
    ax.set_ylabel("Cumulative change in approval (pts)")
    ax.set_title("How presidential approval responds to a gas price shock (95% CI)", loc="left", fontsize=10)
    fig.tight_layout(); fig.savefig(FIG / "approval_irf.png"); plt.close(fig)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
    t = df["month"].dt.to_timestamp()
    for p, g in df.groupby("president", sort=False):
        tt = g["month"].dt.to_timestamp()
        a1.plot(tt, g["approve"], color="#2f6fd0" if PARTY[p] == "D" else "#d0453b", lw=1.4)
    a1.set_ylabel("Approval (%)")
    a1.set_title("Gallup presidential approval (blue = D, red = R)", loc="left", fontsize=10)
    a2.plot(t, df["real_gas"], color="#b86e0a", lw=1.4)
    a2.set_ylabel("$/gal, 2024 dollars")
    a2.set_title("Real price of regular gasoline", loc="left", fontsize=10)
    fig.tight_layout(); fig.savefig(FIG / "approval_gas_timeline.png"); plt.close(fig)


if __name__ == "__main__":
    main()
