"""Pre-election forecast for the 2026 midterm, made with the models fit on 1978-2022.

Written before polls close on Nov 3, 2026 and timestamped, so it can be scored
honestly afterward (see score_2026.py).

Two models are compared:
  A. swing ~ approval              (the benchmark)
  B. swing ~ gas_chg_2y + approval (does adding gas prices help?)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
MANUAL = ROOT / "data" / "manual"
REPORTS = ROOT / "reports"
OUT_JSON = REPORTS / "forecast_2026.json"


def inputs() -> dict:
    df = pd.read_csv(MANUAL / "inputs_2026.csv").set_index("variable")["value"]
    real_gas_chg = 100 * ((df["gas_oct_2026"] / df["gas_oct_2024"]) / (df["cpi_latest"] / df["cpi_two_years_earlier"]) - 1)
    return {
        "approval": float(df["approval"]),
        "approval_low": float(df["approval_low"]),
        "approval_high": float(df["approval_high"]),
        "gas_price_oct": float(df["gas_oct_2026"]),
        "gas_chg_2y": float(real_gas_chg),
        "inflation_1y": float(100 * (df["cpi_latest"] / df["cpi_one_year_earlier"] - 1)),
    }


def baseline_2024() -> dict:
    """Republican two-party House share (contested districts) and seats in 2024."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from build_dataset import district_results, load_house
    dist = district_results(load_house())
    d24 = dist[dist["year"] == 2024]
    c = d24[d24["contested"]]
    return {
        "rep_share_2024": float(100 * c["R"].sum() / (c["D"].sum() + c["R"].sum())),
        "rep_seats_2024": int((d24["winner"] == "R").sum()),
    }


def main() -> None:
    nat = pd.read_csv(PROC / "national.csv")
    x = inputs()
    base = baseline_2024()

    models = {
        "A_approval_only": smf.ols("swing ~ approval", nat).fit(),
        "B_gas_plus_approval": smf.ols("swing ~ gas_chg_2y + approval", nat).fit(),
    }
    seat_model = smf.ols("seat_change ~ approval", nat).fit()

    def predict(model, approval):
        row = pd.DataFrame([{**x, "approval": approval}])
        p = model.get_prediction(row).summary_frame(alpha=0.2)  # 80% prediction interval
        return {"mean": float(p["mean"].iloc[0]), "lo80": float(p["obs_ci_lower"].iloc[0]),
                "hi80": float(p["obs_ci_upper"].iloc[0])}

    out = {
        "made_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "election": "2026-11-03",
        "president": "Trump", "pres_party": "R",
        "inputs": x, "baseline": base, "models": {},
    }
    for name, m in models.items():
        res = {"central": predict(m, x["approval"])}
        res["approval_low"] = predict(m, x["approval_low"])
        res["approval_high"] = predict(m, x["approval_high"])
        for k in ("central", "approval_low", "approval_high"):
            res[k]["rep_share"] = base["rep_share_2024"] + res[k]["mean"]
        res["formula"] = m.model.formula
        res["r2"] = float(m.rsquared)
        out["models"][name] = res
    seats = predict(seat_model, x["approval"])
    out["seats"] = {
        "change": seats,
        "rep_seats": base["rep_seats_2024"] + seats["mean"],
        "rep_seats_lo80": base["rep_seats_2024"] + seats["lo80"],
        "rep_seats_hi80": base["rep_seats_2024"] + seats["hi80"],
    }
    # Out of sample: approval at 38% is the lowest in the training data (min 38, 2006).
    out["warnings"] = [
        f"Approval {x['approval']:.0f}% is at the bottom of the 1978-2022 range "
        f"({nat['approval'].min():.0f}-{nat['approval'].max():.0f}%), so this is near the edge of the data.",
        "Approval comes from a polling average, not Gallup (discontinued in 2026).",
        "Real gas change uses September CPI because October 2026 CPI is not yet released.",
    ]
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    a, b = out["models"]["A_approval_only"]["central"], out["models"]["B_gas_plus_approval"]["central"]
    print(f"Inputs: approval {x['approval']}%, real gas change {x['gas_chg_2y']:+.1f}%, inflation {x['inflation_1y']:.1f}%")
    print(f"2024 baseline: R share {base['rep_share_2024']:.2f}%, R seats {base['rep_seats_2024']}")
    print(f"Model A (approval): swing {a['mean']:+.2f} pts [80%: {a['lo80']:+.2f}, {a['hi80']:+.2f}] -> R share {a['rep_share']:.1f}%")
    print(f"Model B (gas+appr): swing {b['mean']:+.2f} pts [80%: {b['lo80']:+.2f}, {b['hi80']:+.2f}] -> R share {b['rep_share']:.1f}%")
    s = out["seats"]
    print(f"Seats: change {s['change']['mean']:+.0f} -> R {s['rep_seats']:.0f} [80%: {s['rep_seats_lo80']:.0f}-{s['rep_seats_hi80']:.0f}] (218 = majority)")
    print("Saved", OUT_JSON)


if __name__ == "__main__":
    main()
