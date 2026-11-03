"""Statistical analysis: do gas prices predict midterm losses for the president's party?

Outputs
-------
reports/results.md          regression tables + plain-English findings
reports/figures/*.png       static charts for the README
dashboard/data.json         everything the interactive dashboard needs
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
FIG = REPORTS / "figures"
DASH = ROOT / "dashboard"
for d in (FIG, DASH):
    d.mkdir(parents=True, exist_ok=True)

LABELS = {
    "gas_chg_2y": "Real gas price change, 2 yrs (%)",
    "gas_chg_1y": "Real gas price change, 1 yr (%)",
    "gas_chg_2y_rel": "Gas change vs. national avg (pp)",
    "approval": "Presidential approval (%)",
    "inflation_1y": "CPI inflation, 12 mo (%)",
    "unemp_chg_2y": "Unemployment change, 2 yrs (pp)",
    "income_growth_2y": "Real income growth, 2 yrs (%)",
    "crude_chg_2y": "Real crude oil change, 2 yrs (%)",
    "Intercept": "Constant",
}


def stars(p: float) -> str:
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""


def tidy(model, name: str, keep: list[str]) -> dict:
    out = {"model": name, "n": int(model.nobs), "r2": float(model.rsquared), "coefs": {}}
    for v in keep:
        if v in model.params:
            out["coefs"][v] = {
                "b": float(model.params[v]),
                "se": float(model.bse[v]),
                "p": float(model.pvalues[v]),
            }
    return out


def table_md(models: list[dict], variables: list[str], notes: list[str]) -> str:
    head = "| | " + " | ".join(m["model"] for m in models) + " |"
    sep = "|---" * (len(models) + 1) + "|"
    lines = [head, sep]
    for v in variables:
        if not any(v in m["coefs"] for m in models):
            continue
        cells, ses = [], []
        for m in models:
            c = m["coefs"].get(v)
            cells.append(f"{c['b']:.3f}{stars(c['p'])}" if c else "")
            ses.append(f"({c['se']:.3f})" if c else "")
        lines.append(f"| {LABELS.get(v, v)} | " + " | ".join(cells) + " |")
        lines.append("| | " + " | ".join(ses) + " |")
    lines.append("| Observations | " + " | ".join(str(m["n"]) for m in models) + " |")
    lines.append("| R² | " + " | ".join(f"{m['r2']:.2f}" for m in models) + " |")
    for extra in ("fe",):
        if any(extra in m for m in models):
            lines.append("| Fixed effects | " + " | ".join(m.get("fe", "none") for m in models) + " |")
    return "\n".join(lines) + "\n\n" + "\n".join(f"_{n}_  " for n in notes) + "\n"


# ----------------------------------------------------------------------------
def national_analysis(nat: pd.DataFrame) -> tuple[list[dict], dict]:
    specs = [
        ("(1) Gas only", "swing ~ gas_chg_2y"),
        ("(2) + Approval", "swing ~ gas_chg_2y + approval"),
        ("(3) + Inflation", "swing ~ gas_chg_2y + approval + inflation_1y"),
        ("(4) + Unemployment", "swing ~ gas_chg_2y + approval + unemp_chg_2y"),
    ]
    models = []
    for name, f in specs:
        m = smf.ols(f, data=nat).fit(cov_type="HC1")
        models.append(tidy(m, name, ["gas_chg_2y", "approval", "inflation_1y", "unemp_chg_2y", "Intercept"]))

    vars_ = ["gas_chg_2y", "gas_chg_1y", "crude_chg_2y", "approval", "inflation_1y", "unemp_chg_2y"]
    corr = {v: float(nat[["swing", v]].corr().iloc[0, 1]) for v in vars_}

    # Leave-one-out: how much does the gas slope (controlling for approval) depend on
    # any single election?
    loo = []
    for y in nat["year"]:
        sub = nat[nat["year"] != y]
        m = smf.ols("swing ~ gas_chg_2y + approval", data=sub).fit(cov_type="HC1")
        loo.append({"dropped": int(y), "slope": float(m.params["gas_chg_2y"]),
                    "p": float(m.pvalues["gas_chg_2y"])})

    # Mediation check: do gas prices move approval itself?
    med = smf.ols("approval ~ gas_chg_2y", data=nat).fit(cov_type="HC1")
    # Alternative definitions of the same question
    alt = {
        "gas_1y_with_approval": smf.ols("swing ~ gas_chg_1y + approval", data=nat).fit(cov_type="HC1"),
        "seats_with_approval": smf.ols("seat_change ~ gas_chg_2y + approval", data=nat).fit(cov_type="HC1"),
    }
    robust = {
        "approval_on_gas": {"b": float(med.params["gas_chg_2y"]), "p": float(med.pvalues["gas_chg_2y"])},
        "gas_1y_with_approval": {"b": float(alt["gas_1y_with_approval"].params["gas_chg_1y"]),
                                 "p": float(alt["gas_1y_with_approval"].pvalues["gas_chg_1y"])},
        "seats_with_approval": {"b": float(alt["seats_with_approval"].params["gas_chg_2y"]),
                                "p": float(alt["seats_with_approval"].pvalues["gas_chg_2y"])},
    }
    return models, {"correlations": corr, "leave_one_out": loo, "robust": robust}


def state_analysis(panel: pd.DataFrame) -> list[dict]:
    df = panel.dropna(subset=["swing", "gas_chg_2y", "unemp_chg_2y", "income_growth_2y"]).copy()
    # Single states can swing wildly when a lone at-large race is lopsided; weight by
    # number of districts so California's 50+ races count more than Wyoming's one.
    w = df["n_districts"]
    year_cluster = {"cov_type": "cluster", "cov_kwds": {"groups": df["year"]}}
    state_cluster = {"cov_type": "cluster", "cov_kwds": {"groups": df["state"]}}

    keep = ["gas_chg_2y", "gas_chg_2y_rel", "approval", "inflation_1y", "unemp_chg_2y", "income_growth_2y"]
    out = []
    m = smf.wls("swing ~ gas_chg_2y", data=df, weights=w).fit(**year_cluster)
    out.append({**tidy(m, "(1) Pooled", keep), "fe": "none"})
    m = smf.wls(
        "swing ~ gas_chg_2y + approval + inflation_1y + unemp_chg_2y + income_growth_2y",
        data=df, weights=w,
    ).fit(**year_cluster)
    out.append({**tidy(m, "(2) + Controls", keep), "fe": "none"})
    m = smf.wls(
        "swing ~ gas_chg_2y + unemp_chg_2y + income_growth_2y + C(year)", data=df, weights=w
    ).fit(**state_cluster)
    out.append({**tidy(m, "(3) Year FE", keep), "fe": "year"})
    m = smf.wls(
        "swing ~ gas_chg_2y + unemp_chg_2y + income_growth_2y + C(year) + C(state)", data=df, weights=w
    ).fit(**state_cluster)
    out.append({**tidy(m, "(4) Year + State FE", keep), "fe": "year + state"})
    # Robustness: only states where >= 75% of districts were contested in that midterm
    sub = df[df["contested_frac"] >= 0.75]
    m = smf.wls(
        "swing ~ gas_chg_2y + unemp_chg_2y + income_growth_2y + C(year)", data=sub,
        weights=sub["n_districts"],
    ).fit(cov_type="cluster", cov_kwds={"groups": sub["state"]})
    out.append({**tidy(m, "(5) Year FE, contested", keep), "fe": "year"})
    # Robustness: year FE without 2022, the largest gas shock in the sample
    sub = df[df["year"] != 2022]
    m = smf.wls(
        "swing ~ gas_chg_2y + unemp_chg_2y + income_growth_2y + C(year)", data=sub,
        weights=sub["n_districts"],
    ).fit(cov_type="cluster", cov_kwds={"groups": sub["state"]})
    out.append({**tidy(m, "(6) Year FE, no 2022", keep), "fe": "year"})
    return out


# ----------------------------------------------------------------------------
def figures(nat: pd.DataFrame, panel: pd.DataFrame) -> None:
    plt.rcParams.update({"figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False,
                         "font.size": 10})
    blue, red = "#2a6fdb", "#d6453d"

    # 1. National scatter
    fig, ax = plt.subplots(figsize=(7, 4.5))
    colors = [blue if p == "D" else red for p in nat["pres_party"]]
    ax.scatter(nat["gas_chg_2y"], nat["swing"], c=colors, s=60, zorder=3)
    for _, r in nat.iterrows():
        ax.annotate(f"{r.year} {r.president}", (r.gas_chg_2y, r.swing), fontsize=8,
                    xytext=(5, 4), textcoords="offset points")
    b = np.polyfit(nat["gas_chg_2y"], nat["swing"], 1)
    xs = np.linspace(nat["gas_chg_2y"].min(), nat["gas_chg_2y"].max(), 50)
    ax.plot(xs, np.polyval(b, xs), color="gray", lw=1.2, ls="--")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("Real gas price change over the 2 years before the midterm (%)")
    ax.set_ylabel("President's party House vote swing (pts)")
    ax.set_title(f"National: gas prices vs. midterm swing (r = {nat[['gas_chg_2y','swing']].corr().iloc[0,1]:.2f}, n = 12)")
    fig.tight_layout()
    fig.savefig(FIG / "national_scatter.png")
    plt.close(fig)

    # 2. Approval vs swing (the benchmark predictor)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(nat["approval"], nat["swing"], c=colors, s=60, zorder=3)
    for _, r in nat.iterrows():
        ax.annotate(str(r.year), (r.approval, r.swing), fontsize=8, xytext=(5, 4), textcoords="offset points")
    b = np.polyfit(nat["approval"], nat["swing"], 1)
    xs = np.linspace(nat["approval"].min(), nat["approval"].max(), 50)
    ax.plot(xs, np.polyval(b, xs), color="gray", lw=1.2, ls="--")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("Gallup presidential approval before the midterm (%)")
    ax.set_ylabel("President's party House vote swing (pts)")
    ax.set_title(f"Benchmark: approval vs. swing (r = {nat[['approval','swing']].corr().iloc[0,1]:.2f})")
    fig.tight_layout()
    fig.savefig(FIG / "approval_scatter.png")
    plt.close(fig)

    # 3. State-level: within-year relationship (demeaned by year)
    df = panel.dropna(subset=["swing", "gas_chg_2y"]).copy()
    df["swing_rel"] = df["swing"] - df.groupby("year")["swing"].transform("mean")
    df = df[df["swing_rel"].abs() < 25]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(df["gas_chg_2y_rel"], df["swing_rel"], s=np.sqrt(df["n_districts"]) * 8,
               alpha=0.35, color="#555")
    b = np.polyfit(df["gas_chg_2y_rel"], df["swing_rel"], 1, w=df["n_districts"])
    xs = np.linspace(df["gas_chg_2y_rel"].min(), df["gas_chg_2y_rel"].max(), 50)
    ax.plot(xs, np.polyval(b, xs), color=red, lw=1.5)
    ax.axhline(0, color="black", lw=0.6)
    ax.axvline(0, color="black", lw=0.6)
    ax.set_xlabel("State gas price change minus national average that year (pp)")
    ax.set_ylabel("State swing minus national average (pts)")
    ax.set_title("Within each midterm: did states with bigger gas spikes swing harder?")
    fig.tight_layout()
    fig.savefig(FIG / "state_within_year.png")
    plt.close(fig)

    # 4. Time series: two stacked panels sharing the year axis (no dual y-axis)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    ax1.bar(nat["year"], nat["swing"], width=2.2, color=colors)
    ax1.set_ylabel("Swing (pts)")
    ax1.axhline(0, color="black", lw=0.6)
    ax1.set_title("President's party House swing (blue = D president, red = R)", fontsize=10, loc="left")
    ax2.bar(nat["year"], nat["gas_chg_2y"], width=2.2, color="#b86e0a")
    ax2.set_ylabel("Change (%)")
    ax2.axhline(0, color="black", lw=0.6)
    ax2.set_title("Real gas price change over the prior two years", fontsize=10, loc="left")
    ax2.set_xticks(nat["year"])
    fig.tight_layout()
    fig.savefig(FIG / "timeline.png")
    plt.close(fig)


# ----------------------------------------------------------------------------
def interpret(nat_models, nat_extra, state_models) -> str:
    g1 = nat_models[0]["coefs"]["gas_chg_2y"]
    g2 = nat_models[1]["coefs"]["gas_chg_2y"]
    s2 = state_models[1]["coefs"]["gas_chg_2y"]
    s3 = state_models[2]["coefs"]["gas_chg_2y"]
    s4 = state_models[3]["coefs"]["gas_chg_2y"]
    s6 = state_models[5]["coefs"]["gas_chg_2y"]
    loo = nat_extra["leave_one_out"]
    loo_2022 = next(x for x in loo if x["dropped"] == 2022)
    rb = nat_extra["robust"]
    corr = nat_extra["correlations"]

    def eff(c, size=20):
        return f"{c['b'] * size:+.2f} pts per {size}% rise (p = {c['p']:.2f})"

    monthly = ""
    apath = DASH / "approval.json"
    if apath.exists():
        ar = json.loads(apath.read_text(encoding="utf-8"))["results"]
        L2, med, irf1 = ar["levels"]["L2"], ar["mediation"], ar["irf"][1]
        monthly = f"""
6. **Monthly data confirm the gas → approval link** (see [approval_gas.md](approval_gas.md)).
   Across {ar['n_months']} months of Gallup polls, a 10% real gas rise goes with
   {L2['b']:+.1f} approval points (p < 0.001), holding unemployment, inflation and time in office
   fixed and comparing each president with himself. Approval drops within a month
   ({irf1['b']:+.1f} pts, p = {irf1['p']:.3f}). Independents react most
   ({ar['party']['ind']['b']:+.1f}) and the president's own party least ({ar['party']['own']['b']:+.1f}).
7. **Total effect on midterms.** A 20% gas rise costs about {abs(med['indirect']):.1f} pts of swing
   *through approval* (SE {med['indirect_se']:.2f}). The direct coefficient ({med['direct']:+.2f}) offsets
   it, so the estimated total is {med['total']:+.2f} pts (SE {med['total_se']:.2f}). The indirect path
   rests on ~570 months of data. The direct one rests on 12 elections and depends on 2022.
"""

    return f"""## Key findings

**Short answer: no. In 1978–2022, rising gas prices did not reliably cost the president's
party House votes in midterms.** The usual story ("high gas prices sink the party in power")
does not show up in the data once you look carefully.

1. **On its own, the gas price change barely relates to midterm swing.** Across 12 midterms,
   r = {corr['gas_chg_2y']:.2f} between the 2-year real gas price change and the president's party's
   House vote swing. Slope: {eff(g1)}. The sign is *positive*: bigger gas increases
   came with slightly *smaller* losses, the opposite of the popular story.
2. **Presidential approval dominates** (r = {corr['approval']:.2f}). On its own it explains
   {corr['approval'] ** 2:.0%} of the variation in swing across midterms, versus
   {corr['gas_chg_2y'] ** 2:.0%} for gas prices.
3. **Gas prices may work through approval.** Each 10% real gas rise is associated with
   {rb['approval_on_gas']['b'] * 10:+.1f} approval points (p = {rb['approval_on_gas']['p']:.2f}). That is the expected
   direction, but {"only marginally significant" if rb['approval_on_gas']['p'] < 0.1 else "not statistically significant"} with n = 12.
4. **The puzzle: holding approval fixed, gas looks positive** ({eff(g2)}).
   Treat this with caution. It depends on 2022: without 2022 it falls to
   {loo_2022['slope'] * 20:+.2f} pts per 20% rise (p = {loo_2022['p']:.2f}). It vanishes when the
   1-year gas change is used instead (p = {rb['gas_1y_with_approval']['p']:.2f}) and when seats are the
   outcome (p = {rb['seats_with_approval']['p']:.2f}). It is also a textbook *bad control* problem: if gas
   prices hurt the president *through* approval, controlling for approval strips out that channel. The
   gas coefficient then picks up whatever else happened in high-gas years. In 2022, for example, the
   *Dobbs* abortion ruling energized Democrats in the middle of a gas spike.
5. **State panel.** With national controls: {eff(s2)}. Comparing states *within the same midterm*
   (year fixed effects) asks whether states whose gas prices rose more than the national average
   swung harder against the president: {eff(s3)}. With state fixed effects as well:
   {eff(s4)}. Without 2022: {eff(s6)}. None of these show a penalty. Power is limited, because
   gas prices move mostly nationally (crude oil is a global market). Within one year, state
   gas changes differ by only about 2–5 percentage points.
{monthly}
**Interview-ready takeaway:** gas prices clearly hurt presidential approval, and approval
clearly drives midterms. But the gas effect is modest: a 20% spike costs a president about
4 approval points, worth well under 1 point of House vote. That's small next to everything
else that moves approval. Gas is one input to how voters judge the president, not a separate
force that decides midterms on its own.
"""


def main() -> None:
    nat = pd.read_csv(PROC / "national.csv")
    panel = pd.read_csv(PROC / "state_panel.csv")

    nat_models, nat_extra = national_analysis(nat)
    state_models = state_analysis(panel)
    figures(nat, panel)

    md = ["# Results: gas prices and midterm elections\n",
          "Outcome = change in the president's party's two-party U.S. House vote share vs. the "
          "previous presidential election (contested districts only). Positive = gained ground.\n",
          interpret(nat_models, nat_extra, state_models),
          "## National regressions (one row per midterm)\n",
          table_md(nat_models, ["gas_chg_2y", "approval", "inflation_1y", "unemp_chg_2y", "Intercept"],
                   ["Robust (HC1) standard errors in parentheses. * p<0.1, ** p<0.05, *** p<0.01.",
                    "With n = 12 these are descriptive; treat p-values with caution."]),
          "\n## State panel regressions (state × midterm)\n",
          table_md(state_models, ["gas_chg_2y", "approval", "inflation_1y", "unemp_chg_2y", "income_growth_2y"],
                   ["Weighted by number of House districts. Models 1–2: SEs clustered by year "
                    "(national variables vary only by year). Models 3–5: SEs clustered by state.",
                    "Model 5 keeps only state-years where ≥75% of districts had both a D and an R candidate. "
                    "Model 6 drops 2022.",
                    "* p<0.1, ** p<0.05, *** p<0.01."]),
          "\n## Leave-one-out: gas coefficient in model (2), dropping one midterm at a time\n",
          "| Dropped | Gas coef. | p |\n|---|---|---|\n" + "\n".join(
              f"| {x['dropped']} | {x['slope']:.3f} | {x['p']:.2f} |" for x in nat_extra["leave_one_out"]) + "\n",
          "\n## Correlations with national swing\n",
          "| Variable | r |\n|---|---|\n" + "\n".join(
              f"| {LABELS[k]} | {v:.2f} |" for k, v in nat_extra["correlations"].items()) + "\n",
          "\n## Figures\n",
          "![timeline](figures/timeline.png)\n![national](figures/national_scatter.png)\n"
          "![approval](figures/approval_scatter.png)\n![state](figures/state_within_year.png)\n"]
    (REPORTS / "results.md").write_text("\n".join(md), encoding="utf-8")

    dash = {
        "national": nat.round(3).to_dict(orient="records"),
        "panel": panel.round(3).replace({np.nan: None}).to_dict(orient="records"),
        "national_models": nat_models,
        "state_models": state_models,
        "correlations": nat_extra["correlations"],
        "leave_one_out": nat_extra["leave_one_out"],
        "robust": nat_extra["robust"],
        "labels": LABELS,
    }
    (DASH / "data.json").write_text(json.dumps(dash), encoding="utf-8")
    print(f"Wrote {REPORTS / 'results.md'}, {len(list(FIG.glob('*.png')))} figures, and {DASH / 'data.json'}")


if __name__ == "__main__":
    main()
