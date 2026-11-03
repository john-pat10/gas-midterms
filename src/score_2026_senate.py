"""Score the pre-election 2026 Senate forecast.

Fill in data/manual/senate_results_2026.csv with one row per called race:
    state,winner,rep_share
    NC,D,47.9
winner is R, D, or I. rep_share (Republican % of the two-party vote) is optional.
Uncalled races can be left out and the script scores what's there.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RESULTS = ROOT / "data" / "manual" / "senate_results_2026.csv"


def main():
    fc = json.loads((REPORTS / "forecast_senate_2026.json").read_text(encoding="utf-8"))
    if not RESULTS.exists():
        print("No results file yet:", RESULTS)
        return
    res = pd.read_csv(RESULTS)
    res["rep_won"] = (res.winner.str.upper() == "R").astype(int)

    out = {"races_called": len(res), "models": {}}
    for name, m in fc["models"].items():
        rows = []
        for _, r in res.iterrows():
            f = m["races"][r.state]
            row = {"state": r.state, "winner": r.winner, "p_rep_win": f["p_rep_win"],
                   "called_right": (f["p_rep_win"] > 0.5) == bool(r.rep_won),
                   "brier": (f["p_rep_win"] - r.rep_won) ** 2}
            if "rep_share" in res and pd.notna(r.get("rep_share")):
                row["share_error"] = r.rep_share - f["pred_rep_share"]
            rows.append(row)
        t = pd.DataFrame(rows)
        score = {
            "correct_calls": f"{int(t.called_right.sum())}/{len(t)}",
            "brier_score": float(t.brier.mean()),  # 0 = perfect, 0.25 = coin flip
            "misses": t.loc[~t.called_right, ["state", "winner", "p_rep_win"]].to_dict("records"),
        }
        if "share_error" in t:
            score["mean_share_error"] = float(t.share_error.mean())
        if len(res) == len(m["races"]):
            seats = fc["seats_not_up"]["R"] + int(res.rep_won.sum())
            score["actual_rep_seats"] = seats
            score["predicted_rep_seats"] = m["rep_seats_median"]
            score["inside_80pct_interval"] = m["rep_seats_lo80"] <= seats <= m["rep_seats_hi80"]
        out["models"][name] = score

    (REPORTS / "score_senate_2026.json").write_text(json.dumps(out, indent=2, default=str),
                                                    encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
