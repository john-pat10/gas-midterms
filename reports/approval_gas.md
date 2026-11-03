# Gas prices and presidential approval (monthly, 1977-02 to 2024-12)

574 months of Gallup approval (Carter through Biden), monthly average of polls.
Gaps of up to two months are filled by linear interpolation (2% of months).
Effects are scaled to **a 10% rise in the real (inflation-adjusted) price of gasoline**.
Standard errors are Newey-West (HAC, 12 lags) to allow for autocorrelation.

## 1. Does approval fall when gas prices rise?

| Model | Effect of a 10% real gas rise on approval | R² |
|---|---|---|
| L1: president fixed effects only | -2.31 pts (SE 0.60, p = 0.000) | 0.40 |
| L2: + unemployment, inflation, time in office, rally events | -1.99 pts (SE 0.58, p = 0.001) | 0.54 |
| L3: + each president's own time trend | -1.26 pts (SE 0.46, p = 0.006) | 0.72 |
| D: month-to-month changes, 12 lags (cumulative) | +0.38 pts (SE 1.02, p = 0.708) | |

For comparison, in L2 one extra point of unemployment moves approval
-0.94 pts (p = 0.175), and one extra point of
inflation moves it +0.05 pts (p = 0.923).

## 2. How fast? (cumulative effect of a lasting 10% rise, model D)

| Months after the rise | 0 | 1 | 3 | 6 | 9 | 12 |
|---|---|---|---|---|---|---|
| Approval change (pts) | -0.81 | -1.40 | -1.17 | -1.10 | -0.44 | +0.38 |

## 3. Who reacts? (model L2 by party of respondent)

| Group | Effect of a 10% real gas rise |
|---|---|
| President's own party | -1.11 pts (SE 0.46, p = 0.015) |
| Independents | -2.15 pts (SE 0.62, p = 0.001) |
| Opposition party | -1.76 pts (SE 0.69, p = 0.011) |

## 4. Putting it together: gas → approval → midterm swing

For a 20% real gas rise over the two years before a midterm:

| Path | Effect on president's party swing |
|---|---|
| Gas → approval | -3.81 approval pts (SE 1.12) |
| × approval → swing | +0.174 swing pts per approval pt |
| **Indirect (through approval)** | **-0.67 pts** (SE 0.31) |
| Direct (gas, holding approval fixed) | +0.85 pts (SE 0.38) |
| **Total** | **+0.18 pts** (SE 0.49) |

The indirect path uses model L2 (monthly, ~570 obs). The approval → swing and direct
coefficients come from the 12-midterm national regression, so they are much less precise.
Indirect-effect SE uses the delta method (Sobel).
