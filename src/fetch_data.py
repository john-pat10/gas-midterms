"""Download every raw dataset the project needs into data/raw/.

Each source is cached: if the file already exists it is skipped, so you can
re-run this safely. Delete a file in data/raw/ to force a fresh download.

Sources
-------
- EIA State Energy Data System (SEDS): annual state motor-gasoline prices
- EIA Monthly Energy Review (MER) tables 9.4 and 9.1: monthly national
  retail gasoline and crude oil prices
- MIT Election Data + Science Lab: U.S. House returns 1976-2024 (Harvard Dataverse)
- BEA SAINC1: state per-capita personal income
- BLS public API (v1, no key): state unemployment rates + CPI-U
- Gallup presidential approval: small hand-entered file (see data/manual/)
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (gas-midterms research project)"}

FIRST_YEAR, LAST_YEAR = 1975, 2024

# Two-letter code -> state FIPS (50 states + DC)
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}


def _get(url: str, **kw) -> requests.Response:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"  retry ({e})")
            time.sleep(3)
    raise RuntimeError("unreachable")


def fetch_seds() -> None:
    """State gasoline prices. The full SEDS file is ~85 MB, so keep only gasoline rows."""
    out = RAW / "seds_gasoline_prices.csv"
    if out.exists():
        return
    print("SEDS (EIA state energy data, ~85 MB download)...")
    r = _get("https://www.eia.gov/state/seds/CDF/Complete_SEDS.csv")
    df = pd.read_csv(io.BytesIO(r.content))
    # MGACD = motor gasoline price, transportation sector, $ per million Btu
    # MGTCD = motor gasoline price, all sectors, $ per million Btu
    keep = df[df["MSN"].isin(["MGACD", "MGTCD"])]
    keep.to_csv(out, index=False)
    print(f"  saved {len(keep):,} rows -> {out.name}")


def fetch_mer() -> None:
    for tbl, name in [("T09.04", "mer_retail_gasoline.csv"), ("T09.01", "mer_crude_oil.csv")]:
        out = RAW / name
        if out.exists():
            continue
        print(f"MER table {tbl}...")
        r = _get(f"https://www.eia.gov/totalenergy/data/browser/csv.php?tbl={tbl}")
        out.write_bytes(r.content)


HOUSE_FILE = RAW / "1976-2024-house.tab"


def fetch_house() -> bool:
    """The MIT House file sits behind a Dataverse 'guestbook' form (name, email,
    institution, position), so it has to be downloaded by hand once."""
    if HOUSE_FILE.exists():
        return True
    print(
        "\n!! MANUAL STEP: download the MIT Election Lab U.S. House file\n"
        "   1. Open https://doi.org/10.7910/DVN/IG0UN2\n"
        "   2. Download '1976-2024-house.tab' (fill in the short guestbook form)\n"
        f"   3. Save it as {HOUSE_FILE}\n"
    )
    return False


def fetch_bea_income() -> None:
    out = RAW / "bea_sainc1.csv"
    if out.exists():
        return
    print("BEA state personal income (SAINC)...")
    r = _get("https://apps.bea.gov/regional/zip/SAINC.zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.startswith("SAINC1__ALL_AREAS"))
        out.write_bytes(z.read(name))


def _bls_query(series: list[str], start: int, end: int) -> list[dict]:
    """BLS v1 API: max 25 series and 10 years per request, 25 requests/day."""
    r = requests.post(
        "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        data=json.dumps({"seriesid": series, "startyear": str(start), "endyear": str(end)}),
        headers={**UA, "Content-type": "application/json"},
        timeout=120,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {payload.get('message')}")
    return payload["Results"]["series"]


def fetch_bls() -> None:
    out = RAW / "bls_series.csv"
    if out.exists():
        return
    print("BLS (state unemployment + CPI) -- uses ~15 of the 25 free daily API calls...")
    series = [f"LASST{f}0000000000003" for f in STATE_FIPS.values()] + ["CUUR0000SA0"]
    chunks = [series[i:i + 25] for i in range(0, len(series), 25)]
    rows = []
    for start in range(FIRST_YEAR, LAST_YEAR + 1, 10):
        end = min(start + 9, LAST_YEAR)
        for chunk in chunks:
            for s in _bls_query(chunk, start, end):
                for d in s["data"]:
                    if d["period"].startswith("M") and d["period"] != "M13":
                        rows.append({
                            "series_id": s["seriesID"],
                            "year": int(d["year"]),
                            "month": int(d["period"][1:]),
                            "value": float(d["value"]) if d["value"] not in ("-", "") else None,
                        })
            time.sleep(1)
        print(f"  {start}-{end} done")
    pd.DataFrame(rows).to_csv(out, index=False)


def main() -> None:
    fetch_seds()
    fetch_mer()
    fetch_bea_income()
    fetch_bls()
    if fetch_house():
        print("All raw data present in", RAW)


if __name__ == "__main__":
    main()
