"""Covariance (and correlation) for the three links in the gas -> approval -> midterm chain.

Pairs:
  1. Gas prices  vs  presidential approval   (monthly, 1977-2025)
  2. Approval    vs  midterm swing           (12 midterms, 1978-2022)
  3. Gas prices  vs  midterm swing           (12 midterms, 1978-2022)

Covariance is computed by hand, as in class, then checked against numpy:
    cov(X, Y) = sum((x_i - x_bar) * (y_i - y_bar)) / (n - 1)
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "reports" / "figures"


def covariance_by_hand(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    dx, dy = x - x.mean(), y - y.mean()
    return (dx * dy).sum() / (len(x) - 1), dx, dy


def report(name, x, y, xlab, ylab):
    cov, dx, dy = covariance_by_hand(x, y)
    assert np.isclose(cov, np.cov(x, y)[0, 1])  # matches numpy
    r = cov / (np.std(x, ddof=1) * np.std(y, ddof=1))
    agree = int(((dx * dy) > 0).sum())
    print(f"\n=== {name} (n = {len(x)}) ===")
    print(f"  mean {xlab}: {np.mean(x):.2f}   mean {ylab}: {np.mean(y):.2f}")
    print(f"  covariance:  {cov:+.3f}  ({xlab} units x {ylab} units)")
    print(f"  correlation: {r:+.3f}  (unit-free, -1 to +1)")
    print(f"  {agree} of {len(x)} points move the same direction from their means")
    return cov, r


def walkthrough(df, xcol, ycol, xlab, ylab):
    """The by-hand table: deviations from the mean and their products."""
    _, dx, dy = covariance_by_hand(df[xcol], df[ycol])
    t = pd.DataFrame({
        "year": df["year"], "president": df["president"],
        xlab: df[xcol].round(1), ylab: df[ycol].round(2),
        "x - x_bar": dx.round(2), "y - y_bar": dy.round(2),
        "product": (dx * dy).round(2),
    })
    print(t.to_string(index=False))
    s = (dx * dy).sum()
    print(f"  sum of products = {s:.2f};  / (n-1 = {len(t) - 1})  =  {s / (len(t) - 1):.3f}")


def main():
    nat = pd.read_csv(ROOT / "data/processed/national.csv")
    mon = pd.read_csv(ROOT / "data/processed/monthly_approval.csv").dropna(subset=["approve", "real_gas"])

    pairs = [
        ("1. Gas vs approval (monthly)", mon["real_gas"], mon["approve"],
         "real gas $/gal", "approval %"),
        ("2. Approval vs midterm swing", nat["approval"], nat["swing"],
         "approval %", "swing pts"),
        ("3. Gas change vs midterm swing", nat["gas_chg_2y"], nat["swing"],
         "gas % chg (2y)", "swing pts"),
    ]
    results = [report(*p) for p in pairs]

    print("\n--- By-hand table: approval vs swing ---")
    walkthrough(nat, "approval", "swing", "approval", "swing")
    print("\n--- By-hand table: gas change vs swing ---")
    walkthrough(nat, "gas_chg_2y", "swing", "gas_chg", "swing")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for ax, (name, x, y, xl, yl), (cov, r) in zip(axes, pairs, results):
        ax.scatter(x, y, s=12 if len(x) > 50 else 45, alpha=0.5 if len(x) > 50 else 0.9)
        ax.axvline(np.mean(x), color="gray", lw=0.8, ls="--")
        ax.axhline(np.mean(y), color="gray", lw=0.8, ls="--")
        ax.set(title=f"{name[3:]}\ncov = {cov:+.2f}, r = {r:+.2f}", xlabel=xl, ylabel=yl)
    for ax, xcol in zip(axes[1:], ["approval", "gas_chg_2y"]):
        for _, row in nat.iterrows():
            ax.annotate(str(row["year"]), (row[xcol], row["swing"]), fontsize=7,
                        xytext=(3, 3), textcoords="offset points")
    fig.suptitle("Dashed lines = means. Points in top-right/bottom-left add to covariance; "
                 "top-left/bottom-right subtract.", fontsize=9)
    fig.tight_layout()
    out = FIG / "covariance_pairs.png"
    fig.savefig(out, dpi=150)
    print(f"\nFigure saved: {out}")


if __name__ == "__main__":
    main()
