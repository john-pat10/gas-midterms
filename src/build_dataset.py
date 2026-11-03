"""Turn the raw downloads into two analysis-ready tables:

data/processed/state_panel.csv   one row per state x midterm year (1978-2022)
data/processed/national.csv      one row per midterm year

Key definitions
---------------
Outcome ("swing"): change in the president's party's share of the two-party
U.S. House vote, midterm year vs. the presidential election two years earlier.
Only districts where BOTH a Democrat and a Republican ran are counted, so an
unopposed incumbent (no opponent, or no votes reported) doesn't distort the share.

Gas price change: % change in the inflation-adjusted price of gasoline over
the same two-year window (the time the president's party has "owned" the economy).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANUAL = ROOT / "data" / "manual"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

MIDTERMS = list(range(1978, 2023, 4))
MMBTU_PER_GALLON = 5.253 / 42  # EIA conventional motor gasoline heat content
OCT = 10                       # "as of the election" month for monthly series

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


# ----------------------------------------------------------------------------
# Loaders
# ----------------------------------------------------------------------------
def load_house() -> pd.DataFrame:
    """MIT's .tab export wraps every row in quotes and escapes inner quotes as \\"."""
    text = (RAW / "1976-2024-house.tab").read_text(encoding="utf-8")
    lines = text.splitlines()
    rows = [lines[0]] + [
        (ln[1:-1] if ln.startswith('"') and ln.endswith('"') else ln).replace('\\"', '"')
        for ln in lines[1:]
    ]
    df = pd.read_csv(io.StringIO("\n".join(rows)), low_memory=False, quoting=csv.QUOTE_MINIMAL)
    for col in ["runoff", "special", "writein"]:
        df[col] = df[col].astype(str).str.upper().eq("TRUE")
    # Keep general elections plus Election-Day special "open primaries"
    # (Texas 1996 held these after court-ordered redistricting).
    df = df[~df["writein"] & ((df["stage"] == "GEN") | ((df["stage"] == "PRI") & df["special"]))]
    # Where a district had a regular general election, ignore same-day specials.
    key = ["year", "state_po", "district"]
    regular = (df["stage"] == "GEN") & ~df["special"] & ~df["runoff"]
    has_regular = df[regular].groupby(key).size().rename("has_regular")
    df = df.join(has_regular, on=key)
    df = df[~df["special"] | df["has_regular"].isna()].drop(columns="has_regular")
    df["party"] = df["party"].fillna("").str.upper()
    df["major"] = np.select(
        [df["party"].str.startswith("DEMOCRAT"), df["party"].eq("REPUBLICAN")], ["D", "R"], ""
    )
    return df


def load_approval_polls() -> pd.DataFrame:
    """All Gallup approval polls, with column names unified across the UCSB pages."""
    raw = pd.read_csv(RAW / "gallup_approval_polls.csv")

    def first(*cols):
        out = pd.Series(np.nan, index=raw.index, dtype="object")
        for c in cols:
            if c in raw:
                out = out.fillna(raw[c])
        return out

    start = pd.to_datetime(first("Start Date", "Start date", "Start Date.1"), format="mixed", errors="coerce")
    end = pd.to_datetime(first("End Date", "End Date.1"), format="mixed", errors="coerce")
    # Source typo fix: e.g. one Biden poll's end date reads "2/20/224". When the year is
    # implausible, take it from the poll's start date.
    bad = end.dt.year < 1900
    end[bad] = [e.replace(year=s.year) for e, s in zip(end[bad], start[bad])]
    df = pd.DataFrame({
        "president": raw["president"],
        "end": end,
        "approve": pd.to_numeric(raw["Approving"], errors="coerce"),
        "dem": pd.to_numeric(first("Democrats Approving", "Democratic Approval", "Democrats", "Democrats Opproving"), errors="coerce"),
        "ind": pd.to_numeric(first("Independents Approving", "Independent Approval", "Independents"), errors="coerce"),
        "rep": pd.to_numeric(first("Republicans Approving", "Republican Approval", "Republicans"), errors="coerce"),
        "source": raw["Source"].fillna("gallup").str.lower() if "Source" in raw else "gallup",
    })
    return df.dropna(subset=["end", "approve"]).sort_values("end").reset_index(drop=True)


def midterm_approval(pres: pd.DataFrame) -> pd.Series:
    """Last Gallup approval reading before each Election Day."""
    polls = load_approval_polls()
    polls = polls[polls["source"] == "gallup"]
    out = {}
    for _, p in pres.iterrows():
        before = polls[polls["end"] < pd.Timestamp(p["election_day"])]
        out[p["year"]] = before.iloc[-1]["approve"]
    return pd.Series(out)


def load_cpi() -> pd.DataFrame:
    bls = pd.read_csv(RAW / "bls_series.csv")
    cpi = bls[bls["series_id"] == "CUUR0000SA0"][["year", "month", "value"]].rename(columns={"value": "cpi"})
    return cpi.sort_values(["year", "month"]).reset_index(drop=True)


def load_mer(name: str, msn: str) -> pd.Series:
    """Monthly national series from the EIA Monthly Energy Review, indexed by (year, month)."""
    df = pd.read_csv(RAW / name)
    df = df[df["MSN"] == msn].copy()
    df["value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"] = df["YYYYMM"] // 100
    df["month"] = df["YYYYMM"] % 100
    df = df[df["month"].between(1, 12)].dropna(subset=["value"])
    return df.set_index(["year", "month"])["value"]


# ----------------------------------------------------------------------------
# Election results
# ----------------------------------------------------------------------------
def district_results(house: pd.DataFrame) -> pd.DataFrame:
    """One row per district-year with D and R votes. Fusion candidates (e.g. NY
    Democrat + Working Families lines) have their votes summed across lines."""
    key = ["year", "state_po", "district"]

    def by_candidate(rows: pd.DataFrame) -> pd.DataFrame:
        return (
            rows.groupby(key + ["candidate"])
            .agg(votes=("candidatevotes", "sum"), major=("major", "max"))
            .reset_index()
        )

    # Vote shares use the first-round general election; the seat goes to the
    # runoff winner where a runoff was held (Georgia, Louisiana, Texas 1996).
    cand = by_candidate(house[~house["runoff"]])
    runoff_cand = by_candidate(house[house["runoff"]])
    seat_rows = pd.concat([runoff_cand, cand[~cand.set_index(key).index.isin(runoff_cand.set_index(key).index)]])
    winners = seat_rows.sort_values("votes").groupby(key).tail(1)
    winners = winners.set_index(key)["major"].rename("winner")
    major = cand[cand["major"] != ""]
    wide = major.pivot_table(
        index=["year", "state_po", "district"], columns="major", values="votes", aggfunc="sum"
    ).reindex(columns=["D", "R"])
    wide = wide.join(winners)
    wide["contested"] = (wide["D"] > 0) & (wide["R"] > 0)
    return wide.reset_index()


def state_vote(dist: pd.DataFrame) -> pd.DataFrame:
    c = dist[dist["contested"]]
    contested = c.groupby(["year", "state_po"])[["D", "R"]].sum()
    contested["dem_share"] = contested["D"] / (contested["D"] + contested["R"])
    counts = dist.groupby(["year", "state_po"]).agg(
        n_districts=("district", "nunique"), n_contested=("contested", "sum")
    )
    return contested[["dem_share"]].join(counts, how="right").reset_index()


def national_house(dist: pd.DataFrame) -> pd.DataFrame:
    c = dist[dist["contested"]].groupby("year")[["D", "R"]].sum()
    nat = pd.DataFrame({"dem_share": c["D"] / (c["D"] + c["R"])})
    seats = dist.groupby("year")["winner"].value_counts().unstack(fill_value=0)
    nat["dem_seats"] = seats.get("D", 0)
    nat["rep_seats"] = seats.get("R", 0)
    return nat


# ----------------------------------------------------------------------------
# Economics
# ----------------------------------------------------------------------------
def pct(new, old):
    return 100 * (new / old - 1)


def build_national(dist: pd.DataFrame, pres: pd.DataFrame) -> pd.DataFrame:
    cpi = load_cpi().set_index(["year", "month"])["cpi"]
    # Unleaded regular is the series people see at the pump; it begins in 1976.
    gas = load_mer("mer_retail_gasoline.csv", "RUUCUUS")
    crude = load_mer("mer_crude_oil.csv", "RACPUUS")  # refiner acquisition cost, composite
    real_gas = gas / cpi * cpi.loc[(2024, OCT)]
    real_crude = crude / cpi * cpi.loc[(2024, OCT)]

    house = national_house(dist)
    bls = pd.read_csv(RAW / "bls_series.csv")
    # National unemployment = labor-force-weighted average isn't in our pull, so use
    # the simple mean of state rates (close to the official national rate).
    ur = bls[bls["series_id"].str.startswith("LASST")].groupby(["year", "month"])["value"].mean()

    rows = []
    for _, p in pres.iterrows():
        y = int(p["year"])
        sign = 1 if p["pres_party"] == "D" else -1
        share_now = house.loc[y, "dem_share"]
        share_prev = house.loc[y - 2, "dem_share"]
        seats_now = house.loc[y, "dem_seats"] if sign == 1 else house.loc[y, "rep_seats"]
        seats_prev = house.loc[y - 2, "dem_seats"] if sign == 1 else house.loc[y - 2, "rep_seats"]
        rows.append({
            "year": y,
            "president": p["president"],
            "pres_party": p["pres_party"],
            "approval": p["gallup_approval"],
            "pres_party_share": 100 * (share_now if sign == 1 else 1 - share_now),
            "swing": 100 * sign * (share_now - share_prev),
            "seat_change": int(seats_now - seats_prev),
            "gas_price_oct": gas.loc[(y, OCT)],
            "real_gas_price_oct": real_gas.loc[(y, OCT)],
            "gas_chg_2y": pct(real_gas.loc[(y, OCT)], real_gas.loc[(y - 2, OCT)]),
            "gas_chg_1y": pct(real_gas.loc[(y, OCT)], real_gas.loc[(y - 1, OCT)]),
            "crude_chg_2y": pct(real_crude.loc[(y, OCT)], real_crude.loc[(y - 2, OCT)]),
            "inflation_1y": pct(cpi.loc[(y, OCT)], cpi.loc[(y - 1, OCT)]),
            "unemp_oct": ur.loc[(y, OCT)],
            "unemp_chg_2y": ur.loc[(y, OCT)] - ur.loc[(y - 2, OCT)],
        })
    return pd.DataFrame(rows)


def build_state_panel(dist: pd.DataFrame, pres: pd.DataFrame, national: pd.DataFrame) -> pd.DataFrame:
    sv = state_vote(dist).set_index(["year", "state_po"])

    cpi_annual = load_cpi().groupby("year")["cpi"].mean()
    deflator = cpi_annual / cpi_annual.loc[2024]

    seds = pd.read_csv(RAW / "seds_gasoline_prices.csv")
    seds = seds[seds["MSN"] == "MGACD"].rename(columns={"StateCode": "state_po", "Year": "year"})
    seds["gas_price"] = seds["Data"] * MMBTU_PER_GALLON  # $/MMBtu -> approx $/gallon
    seds["real_gas_price"] = seds["gas_price"] / seds["year"].map(deflator)
    gas = seds.set_index(["year", "state_po"])["real_gas_price"]

    bls = pd.read_csv(RAW / "bls_series.csv")
    from fetch_data import STATE_FIPS
    fips_to_po = {v: k for k, v in STATE_FIPS.items()}
    ur = bls[bls["series_id"].str.startswith("LASST")].copy()
    ur["state_po"] = ur["series_id"].str[5:7].map(fips_to_po)
    ur = ur[ur["month"] == OCT].set_index(["year", "state_po"])["value"]

    bea = pd.read_csv(RAW / "bea_sainc1.csv", encoding="latin1")
    bea = bea[bea["LineCode"] == 3]
    bea["fips"] = bea["GeoFIPS"].str.strip().str.strip('"').str[:2]
    bea["state_po"] = bea["fips"].map(fips_to_po)
    bea = bea.dropna(subset=["state_po"])
    year_cols = [c for c in bea.columns if c.isdigit()]
    inc = bea.melt(id_vars="state_po", value_vars=year_cols, var_name="year", value_name="income")
    inc["year"] = inc["year"].astype(int)
    inc["income"] = pd.to_numeric(inc["income"], errors="coerce")
    inc["real_income"] = inc["income"] / inc["year"].map(deflator)
    inc = inc.set_index(["year", "state_po"])["real_income"]

    nat = national.set_index("year")
    rows = []
    for _, p in pres.iterrows():
        y = int(p["year"])
        sign = 1 if p["pres_party"] == "D" else -1
        for s in STATES:
            def get(series, yr):
                return series.get((yr, s), np.nan)
            now, prev = get(sv["dem_share"], y), get(sv["dem_share"], y - 2)
            rows.append({
                "year": y,
                "state": s,
                "pres_party": p["pres_party"],
                "swing": 100 * sign * (now - prev),
                "pres_party_share": 100 * (now if sign == 1 else 1 - now),
                "n_districts": get(sv["n_districts"], y),
                "contested_frac": get(sv["n_contested"], y) / get(sv["n_districts"], y),
                "real_gas_price": get(gas, y),
                "gas_chg_2y": pct(get(gas, y), get(gas, y - 2)),
                "gas_chg_1y": pct(get(gas, y), get(gas, y - 1)),
                "unemp": get(ur, y),
                "unemp_chg_2y": get(ur, y) - get(ur, y - 2),
                "income_growth_2y": pct(get(inc, y), get(inc, y - 2)),
                # national context, repeated for every state
                "approval": nat.loc[y, "approval"],
                "inflation_1y": nat.loc[y, "inflation_1y"],
                "crude_chg_2y": nat.loc[y, "crude_chg_2y"],
            })
    panel = pd.DataFrame(rows)
    # Gas change relative to the national average that year: isolates state-specific shocks
    panel["gas_chg_2y_rel"] = panel["gas_chg_2y"] - panel.groupby("year")["gas_chg_2y"].transform("mean")
    return panel


def main() -> None:
    pres = pd.read_csv(MANUAL / "presidents.csv")
    pres["gallup_approval"] = pres["year"].map(midterm_approval(pres))
    house = load_house()
    dist = district_results(house)

    national = build_national(dist, pres)
    panel = build_state_panel(dist, pres, national)

    national.to_csv(OUT / "national.csv", index=False)
    panel.to_csv(OUT / "state_panel.csv", index=False)
    usable = panel.dropna(subset=["swing", "gas_chg_2y"])
    print(f"national.csv: {len(national)} midterms")
    print(f"state_panel.csv: {len(panel)} rows, {len(usable)} usable (have both a swing and gas change)")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    main()
