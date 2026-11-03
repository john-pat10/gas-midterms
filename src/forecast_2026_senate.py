"""Pre-election 2026 Senate forecast: a "fundamentals only" model.

Idea: take each state's 2024 presidential vote as its baseline lean, shift every
state by the national swing our House models predict, then add uncertainty.
No polls and no candidate information are used, so this tests how far the
national environment alone gets you in the Senate.

  predicted R share in state = Trump 2024 two-party share + predicted national swing

Uncertainty (simulated 100,000 times):
  - national error: one shared draw per simulation, SD taken from the House
    model's own 80% interval (every race moves together)
  - state error: independent per race, SD = 5 points (an assumption covering
    candidates, incumbency and local issues; NOT estimated from our data)

Inputs entered from Claude's pre-election knowledge (through mid-2026) because
live sources were unreachable on election day; see data/manual/senate_2026_races.csv.
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
N_SIMS = 100_000
STATE_SD = 5.0
Z80 = 1.2816

# Seats NOT up in 2026: 53 R / 47 D+I before the election, minus seats being contested
R_NOT_UP, D_NOT_UP = 31, 34   # D includes King (ME) and Sanders (VT), who caucus with Democrats


def main():
    import sys
    target = REPORTS / "forecast_senate_2026.json"
    if target.exists() and "--force" not in sys.argv:
        print(f"Forecast already locked in {target}; not overwriting (use --force).")
        return
    house = json.loads((REPORTS / "forecast_2026.json").read_text(encoding="utf-8"))
    races = pd.read_csv(ROOT / "data/manual/senate_2026_races.csv")
    races["r_base"] = 100 * races.trump_2024_pct / (races.trump_2024_pct + races.harris_2024_pct)

    rng = np.random.default_rng(2026)
    out = {"made_at": datetime.now().astimezone().isoformat(timespec="minutes"),
           "timing_note": "Made on election day (see made_at), just after the first polls closed "
                          "(6 PM ET) but before any results were viewed. Inputs come from "
                          "pre-election knowledge only.",
           "method": __doc__.strip(), "state_sd_assumption": STATE_SD,
           "seats_not_up": {"R": R_NOT_UP, "D_and_caucus": D_NOT_UP},
           "control_rule": "Republicans keep control with 50+ seats (VP Vance breaks ties); "
                           "Democrats need 51.",
           "models": {}}

    for name in ["A_approval_only", "B_gas_plus_approval"]:
        c = house["models"][name]["central"]
        swing, nat_sd = c["mean"], (c["hi80"] - c["lo80"]) / (2 * Z80)
        pred = races.r_base.values + swing
        nat = rng.normal(0, nat_sd, (N_SIMS, 1))
        st = rng.normal(0, STATE_SD, (N_SIMS, len(races)))
        r_win = (pred + nat + st) > 50
        r_seats = R_NOT_UP + r_win.sum(axis=1)
        p_r = r_win.mean(axis=0)
        out["models"][name] = {
            "national_swing": swing, "national_sd": nat_sd,
            "rep_seats_mean": float(r_seats.mean()),
            "rep_seats_median": int(np.median(r_seats)),
            "rep_seats_lo80": int(np.percentile(r_seats, 10)),
            "rep_seats_hi80": int(np.percentile(r_seats, 90)),
            "p_rep_control": float((r_seats >= 50).mean()),
            "p_dem_control": float((r_seats <= 49).mean()),
            "races": {s: {"pred_rep_share": round(float(p), 2), "p_rep_win": round(float(q), 3),
                          "holding": h}
                      for s, p, q, h in zip(races.state, pred, p_r, races.holding_party)},
        }
        m = out["models"][name]
        print(f"\n{name}: swing {swing:+.1f}  ->  R seats {m['rep_seats_median']} "
              f"(80%: {m['rep_seats_lo80']}-{m['rep_seats_hi80']}), "
              f"P(R control) = {m['p_rep_control']:.0%}")

    races["pred"] = races.r_base + house["models"]["A_approval_only"]["central"]["mean"]
    races["p_rep_win"] = [out["models"]["A_approval_only"]["races"][s]["p_rep_win"] for s in races.state]
    close = races[(races.p_rep_win > 0.1) & (races.p_rep_win < 0.9)].sort_values("p_rep_win")
    print("\nCompetitive races (model A):")
    print(close[["state", "holding_party", "r_base", "pred", "p_rep_win"]].round(2).to_string(index=False))

    (REPORTS / "forecast_senate_2026.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSaved {REPORTS / 'forecast_senate_2026.json'}")


if __name__ == "__main__":
    main()
