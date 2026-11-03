"""Score the pre-election 2026 forecast against unofficial results.

Fill in data/manual/results_2026_prelim.csv (one row per update), then run this.
Uses the most recent row. Results stay "preliminary" until certified; the
official MIT Election Lab file usually arrives months later.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RESULTS = ROOT / "data" / "manual" / "results_2026_prelim.csv"


def main() -> None:
    fc = json.loads((REPORTS / "forecast_2026.json").read_text(encoding="utf-8"))
    if not RESULTS.exists():
        print("No results file yet:", RESULTS)
        return
    r = pd.read_csv(RESULTS).sort_values("as_of").iloc[-1]
    rep_share = 100 * r["rep_votes"] / (r["rep_votes"] + r["dem_votes"])
    actual_swing = rep_share - fc["baseline"]["rep_share_2024"]

    scored = {}
    for name, m in fc["models"].items():
        c = m["central"]
        scored[name] = {
            "predicted_swing": c["mean"],
            "error": actual_swing - c["mean"],
            "inside_80pct_interval": bool(c["lo80"] <= actual_swing <= c["hi80"]),
        }
    seats = fc["seats"]
    out = {
        "as_of": str(r["as_of"]),
        "source": str(r["source"]),
        "pct_counted_note": str(r.get("note", "")),
        "actual_rep_share": rep_share,
        "actual_swing": actual_swing,
        "rep_seats_won": int(r["rep_seats"]),
        "dem_seats_won": int(r["dem_seats"]),
        "seats_uncalled": int(435 - r["rep_seats"] - r["dem_seats"]),
        "predicted_rep_seats": seats["rep_seats"],
        "seats_inside_80pct_interval": bool(seats["rep_seats_lo80"] <= r["rep_seats"] <= seats["rep_seats_hi80"]),
        "models": scored,
        "gas_helped": abs(scored["B_gas_plus_approval"]["error"]) < abs(scored["A_approval_only"]["error"]),
    }
    (REPORTS / "score_2026.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
