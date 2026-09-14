"""
Loads and normalizes the Toronto Police traffic collision CSV.
"""

import os
import pandas as pd

DATA_PATH = os.environ.get("TORONTO_CSV_PATH", "../data/toronto.csv")

TRUTHY_STRINGS = {"yes", "y", "true", "1"}

INVOLVEMENT_COLS = ["AUTOMOBILE", "MOTORCYCLE", "PASSENGER", "BICYCLE", "PEDESTRIAN"]
SEVERITY_COLS = ["FATALITIES", "INJURY_COLLISIONS", "FTR_COLLISIONS", "PD_COLLISIONS"]

SEVERITY_LABELS = {
    "FATALITIES": "Fatal",
    "INJURY_COLLISIONS": "Injury",
    "FTR_COLLISIONS": "Fail to remain",
    "PD_COLLISIONS": "Property damage",
}

# Severity priority when a row needs a single label (worst outcome wins)
SEVERITY_PRIORITY = ["FATALITIES", "INJURY_COLLISIONS", "FTR_COLLISIONS", "PD_COLLISIONS"]


def _to_flag(series: pd.Series) -> pd.Series:
    """Normalize a 0/1, True/False, or Yes/No column into clean 0/1 ints."""
    if series.dtype == object:
        return series.astype(str).str.strip().str.lower().isin(TRUTHY_STRINGS).astype(int)
    return pd.to_numeric(series, errors="coerce").fillna(0).clip(upper=1).astype(int)


def _to_count(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        flagged = series.astype(str).str.strip().str.lower().isin(TRUTHY_STRINGS)
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.fillna(flagged.astype(int))
    return pd.to_numeric(series, errors="coerce").fillna(0)


def _hour_bucket(h) -> str:
    if pd.isna(h):
        return "Unknown"
    h = int(h)
    if 5 <= h <= 11:
        return "Morning"
    if 12 <= h <= 16:
        return "Afternoon"
    if 17 <= h <= 20:
        return "Evening"
    return "Night"


class CollisionData:
    def __init__(self, path: str = DATA_PATH):
        self.path = path
        self.df = self._load(path)

    def _load(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path, low_memory=False)

        for col in SEVERITY_COLS:
            if col in df.columns:
                df[col] = _to_count(df[col])
            else:
                df[col] = 0

        for col in INVOLVEMENT_COLS:
            if col in df.columns:
                df[col] = _to_flag(df[col])
            else:
                df[col] = 0

        if "OCC_HOUR" in df.columns:
            df["OCC_HOUR"] = pd.to_numeric(df["OCC_HOUR"], errors="coerce")
            df["HOUR_BUCKET"] = df["OCC_HOUR"].apply(_hour_bucket)
        else:
            df["OCC_HOUR"] = pd.NA
            df["HOUR_BUCKET"] = "Unknown"

        if "OCC_YEAR" in df.columns:
            df["OCC_YEAR"] = pd.to_numeric(df["OCC_YEAR"], errors="coerce")

        for col in ["LAT_WGS84", "LONG_WGS84"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Single worst-outcome severity label per row, for the matrix chart
        def worst_severity(row):
            for col in SEVERITY_PRIORITY:
                if row[col] and row[col] > 0:
                    return SEVERITY_LABELS[col]
            return "Property damage"

        df["SEVERITY_LABEL"] = df[SEVERITY_PRIORITY].gt(0).idxmax(axis=1).map(SEVERITY_LABELS)
        # idxmax picks the first True column per row; rows with no True land on
        # the first column by default, so patch those explicitly to "Property damage".
        no_flag = ~df[SEVERITY_PRIORITY].gt(0).any(axis=1)
        df.loc[no_flag, "SEVERITY_LABEL"] = "Property damage"

        for col in ["DIVISION", "NEIGHBOURHOOD_158", "HOOD_158", "OCC_DOW", "OCC_MONTH"]:
            if col not in df.columns:
                df[col] = "Unknown"
            df[col] = df[col].fillna("Unknown")

        return df

    def filtered(self, year_from=None, year_to=None) -> pd.DataFrame:
        df = self.df
        if year_from is not None:
            df = df[df["OCC_YEAR"] >= year_from]
        if year_to is not None:
            df = df[df["OCC_YEAR"] <= year_to]
        return df

    def year_bounds(self):
        years = self.df["OCC_YEAR"].dropna()
        if years.empty:
            return None, None
        return int(years.min()), int(years.max())
