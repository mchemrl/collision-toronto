
"""
Toronto Streets, By the Numbers — backend API.

Loads the collision CSV once at startup, precomputes/aggregates in pandas,
and serves small JSON payloads to the frontend. The dashboard fetches only
aggregates, never the raw 100MB+ file, so it stays fast regardless of the
source data's size.

Run:
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8000

The CSV path defaults to "../data/toronto.csv" (relative to wherever you
launch uvicorn from). Override with:
    TORONTO_CSV_PATH=/absolute/path/to/toronto.csv uvicorn app:app --reload
"""

from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from data_loader import CollisionData, INVOLVEMENT_COLS, SEVERITY_LABELS, SEVERITY_PRIORITY

app = FastAPI(title="Toronto Traffic Collisions API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    DATA = CollisionData()
except FileNotFoundError as exc:
    raise SystemExit(
        f"\nCould not find the collisions CSV at '{exc.filename}'.\n"
        "Set TORONTO_CSV_PATH to point at your toronto.csv, e.g.\n"
        "  TORONTO_CSV_PATH=../data/toronto.csv uvicorn app:app --reload\n"
    ) from exc


def _year_params(year_from: Optional[int], year_to: Optional[int]) -> pd.DataFrame:
    return DATA.filtered(year_from, year_to)


@app.get("/api/health")
def health():
    return {"status": "ok", "rows": int(len(DATA.df))}


@app.get("/api/meta")
def meta():
    """Bounds/options used to populate the dashboard's filter controls."""
    y_min, y_max = DATA.year_bounds()
    divisions = sorted(d for d in DATA.df["DIVISION"].unique() if d != "Unknown")
    return {
        "year_min": y_min,
        "year_max": y_max,
        "divisions": divisions,
        "days_of_week": sorted(d for d in DATA.df["OCC_DOW"].dropna().unique()),
    }


@app.get("/api/summary")
def summary(year_from: Optional[int] = None, year_to: Optional[int] = None):
    df = _year_params(year_from, year_to)
    total = len(df)
    fatal = int(df["FATALITIES"].sum())
    injuries = int(df["INJURY_COLLISIONS"].gt(0).sum())
    pedestrian = int(df["PEDESTRIAN"].sum())
    cyclist = int(df["BICYCLE"].sum())

    peak_hour_row = (
        df[df["PEDESTRIAN"] > 0]["OCC_HOUR"].dropna().astype(int).value_counts().idxmax()
        if (df["PEDESTRIAN"] > 0).any()
        else None
    )

    top_division = (
        df.loc[df["DIVISION"] != "NSA", "DIVISION"].value_counts().idxmax()
        if not df.loc[df["DIVISION"] != "NSA", "DIVISION"].empty
        else None
    )

    return {
        "total_collisions": total,
        "total_fatalities": fatal,
        "collisions_with_injury": injuries,
        "pedestrian_involved": pedestrian,
        "cyclist_involved": cyclist,
        "peak_pedestrian_hour": int(peak_hour_row) if peak_hour_row is not None else None,
        "top_division": top_division,
    }


@app.get("/api/yearly")
def yearly(year_from: Optional[int] = None, year_to: Optional[int] = None):
    df = _year_params(year_from, year_to)
    grouped = df.groupby("OCC_YEAR").agg(
        fatal=("FATALITIES", lambda s: int((s > 0).sum())),
        injury=("INJURY_COLLISIONS", lambda s: int((s > 0).sum())),
        property_damage=("PD_COLLISIONS", lambda s: int((s > 0).sum())),
    )
    grouped = grouped[grouped.index.notna()].sort_index()
    return {
        "years": [int(y) for y in grouped.index],
        "fatal": grouped["fatal"].tolist(),
        "injury": grouped["injury"].tolist(),
        "property_damage": grouped["property_damage"].tolist(),
    }


HOUR_ORDER = list(range(24))


@app.get("/api/hourly")
def hourly(year_from: Optional[int] = None, year_to: Optional[int] = None):
    df = _year_params(year_from, year_to)
    df = df.dropna(subset=["OCC_HOUR"]).copy()
    df["OCC_HOUR"] = df["OCC_HOUR"].astype(int)

    all_counts = df.groupby("OCC_HOUR").size().reindex(HOUR_ORDER, fill_value=0)
    ped_counts = (
        df[df["PEDESTRIAN"] > 0].groupby("OCC_HOUR").size().reindex(HOUR_ORDER, fill_value=0)
    )
    bike_counts = (
        df[df["BICYCLE"] > 0].groupby("OCC_HOUR").size().reindex(HOUR_ORDER, fill_value=0)
    )

    return {
        "hours": HOUR_ORDER,
        "all": all_counts.tolist(),
        "pedestrian": ped_counts.tolist(),
        "bicycle": bike_counts.tolist(),
    }


@app.get("/api/matrix")
def matrix(year_from: Optional[int] = None, year_to: Optional[int] = None):
    df = _year_params(year_from, year_to)
    # Fatal collisions are rare enough that they'd barely register on this
    # chart, and they deserve their own comparison anyway — see
    # /api/fatal-by-road-user for that.
    severities = [s for s in SEVERITY_LABELS.values() if s != "Fatal"]
    rows = []
    for road_user in INVOLVEMENT_COLS:
        subset = df[df[road_user] > 0]
        counts = subset["SEVERITY_LABEL"].value_counts()
        rows.append({
            "road_user": road_user.title(),
            "counts": {sev: int(counts.get(sev, 0)) for sev in severities},
            "total": int(len(subset)),
        })
    return {"severities": severities, "rows": rows}


@app.get("/api/fatal-by-road-user")
def fatal_by_road_user(year_from: Optional[int] = None, year_to: Optional[int] = None):
    """Dedicated fatal-collision comparison: for each road-user type, what
    share of ITS collisions turned out fatal. Frequency (how often each type
    is involved at all) is covered on the matrix page — this page is about
    risk-per-incident instead, which is where pedestrians and cyclists stand
    out sharply despite being a small slice of total collision volume."""
    df = _year_params(year_from, year_to)
    rows = []
    for road_user in INVOLVEMENT_COLS:
        subset = df[df[road_user] > 0]
        total = int(len(subset))
        fatal = int((subset["FATALITIES"] > 0).sum())
        rate = round(fatal / total * 100, 3) if total else 0
        rows.append({
            "road_user": road_user.title(),
            "total_collisions": total,
            "fatal_collisions": fatal,
            "fatality_rate_pct": rate,
        })
    rows.sort(key=lambda r: r["fatality_rate_pct"], reverse=True)

    overall_total = int(len(df))
    overall_fatal = int((df["FATALITIES"] > 0).sum())
    overall_rate = round(overall_fatal / overall_total * 100, 3) if overall_total else 0

    return {"rows": rows, "overall_fatality_rate_pct": overall_rate, "total_fatalities": overall_fatal}


@app.get("/api/factors")
def factors(
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    top_n: int = 10,
):
    df = _year_params(year_from, year_to)
    # NSA ("No Specified Address") isn't a real division — it's a catch-all
    # for collisions with no verified location, so it doesn't belong in a
    # "which division needs attention" ranking.
    df = df[df["DIVISION"] != "NSA"]
    severities = [s for s in SEVERITY_LABELS.values() if s != "Fatal"]

    top_divisions = df["DIVISION"].value_counts().head(top_n).index.tolist()
    rows = []
    for division in top_divisions:
        subset = df[df["DIVISION"] == division]
        counts = subset["SEVERITY_LABEL"].value_counts()
        rows.append({
            "division": division,
            "counts": {sev: int(counts.get(sev, 0)) for sev in severities},
            "total": int(len(subset)),
        })
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"severities": severities, "rows": rows}


@app.get("/api/pedestrian-cumulative")
def pedestrian_cumulative(
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    dow: Optional[str] = None,
):
    df = _year_params(year_from, year_to)
    df = df[df["PEDESTRIAN"] > 0]
    if dow:
        df = df[df["OCC_DOW"].astype(str).str.lower() == dow.lower()]

    df = df.dropna(subset=["OCC_HOUR"]).copy()
    df["OCC_HOUR"] = df["OCC_HOUR"].astype(int)

    counts = df.groupby("OCC_HOUR").size().reindex(HOUR_ORDER, fill_value=0)
    cumulative = counts.cumsum()
    total = int(counts.sum())
    pct = (cumulative / total * 100).round(1) if total else cumulative

    return {
        "hours": HOUR_ORDER,
        "counts": counts.tolist(),
        "cumulative": cumulative.tolist(),
        "cumulative_pct": pct.tolist(),
        "total": total,
    }


DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@app.get("/api/pedestrian-hourly-profile")
def pedestrian_hourly_profile(year_from: Optional[int] = None, year_to: Optional[int] = None):
    """How many pedestrian collisions typically happen at each hour of the
    day, averaged across the number of days in the selected range — so the
    answer is "on an average day, about how many happen at 8am" rather than
    a multi-year raw total. This is a plain per-hour count (not cumulative),
    which is what actually answers "when is it worst," since a cumulative
    curve is *always* near-zero at hour 0 and 100% by hour 23 regardless of
    the underlying pattern — that shape reflects the math of a running
    total, not anything about collision risk."""
    df = _year_params(year_from, year_to)
    ped = df[df["PEDESTRIAN"] > 0].dropna(subset=["OCC_HOUR"]).copy()
    ped["OCC_HOUR"] = ped["OCC_HOUR"].astype(int)

    # Number of distinct calendar days covered, to turn multi-year totals
    # into an "average day" rate. Falls back to a year-count estimate if
    # OCC_DATE isn't usable.
    days_covered = None
    if "OCC_DATE" in df.columns:
        try:
            days_covered = df["OCC_DATE"].astype(str).nunique()
        except Exception:
            days_covered = None
    if not days_covered:
        y_from = int(df["OCC_YEAR"].min()) if not df["OCC_YEAR"].dropna().empty else 0
        y_to = int(df["OCC_YEAR"].max()) if not df["OCC_YEAR"].dropna().empty else 0
        days_covered = max((y_to - y_from + 1) * 365, 1)

    total_by_hour = ped.groupby("OCC_HOUR").size().reindex(HOUR_ORDER, fill_value=0)
    avg_by_hour = (total_by_hour / days_covered).round(3)

    peak_hour = int(total_by_hour.idxmax()) if total_by_hour.sum() > 0 else None

    return {
        "hours": HOUR_ORDER,
        "total": total_by_hour.tolist(),
        "average_per_day": avg_by_hour.tolist(),
        "days_covered": int(days_covered),
        "peak_hour": peak_hour,
    }


@app.get("/api/pedestrian-cumulative-by-dow")
def pedestrian_cumulative_by_dow(year_from: Optional[int] = None, year_to: Optional[int] = None):
    """Same metric as /api/pedestrian-cumulative, but returns all 7 days at
    once so the frontend can overlay them on a single chart instead of
    toggling between days."""
    df = _year_params(year_from, year_to)
    df = df[df["PEDESTRIAN"] > 0].dropna(subset=["OCC_HOUR"]).copy()
    df["OCC_HOUR"] = df["OCC_HOUR"].astype(int)

    series = {}
    for day in DAYS_OF_WEEK:
        day_df = df[df["OCC_DOW"].astype(str).str.lower() == day.lower()]
        counts = day_df.groupby("OCC_HOUR").size().reindex(HOUR_ORDER, fill_value=0)
        total = int(counts.sum())
        cumulative_pct = (counts.cumsum() / total * 100).round(1) if total else counts.cumsum()
        series[day] = {
            "counts": counts.tolist(),
            "cumulative_pct": cumulative_pct.tolist(),
            "total": total,
        }

    return {"hours": HOUR_ORDER, "days": DAYS_OF_WEEK, "series": series}


# Each solution's real-world rationale, plus which columns in the dataset we
# use as the closest available proxy for "where this cause shows up" — the
# raw data has no explicit collision-cause field, so these are reasonable
# stand-ins, not ground truth.
SOLUTION_DEFINITIONS = {
    "rumble_strips": {
        "label": "Rumble strips",
        "cause": "Aggressive / distracted driving",
        "how": "Creates vibration and sound to alert distracted or drowsy drivers drifting out of their lane.",
        "proxy": "Highest share of fail-to-remain collisions (a behavioural-risk signal).",
    },
    "intersection": {
        "label": "Intersection safety",
        "cause": "At intersections",
        "how": "Redesigning intersections with better signals, clear markings, and protected phases for pedestrians reduces conflict points.",
        "proxy": "Highest combined pedestrian + cyclist collision volume.",
    },
    "lighting": {
        "label": "Street lighting",
        "cause": "Night time",
        "how": "Increases visibility at intersections and along corridors, critical for spotting pedestrians who are disproportionately struck after dark.",
        "proxy": "Highest pedestrian collision volume during night hours (9pm–5am).",
    },
    "stop_signs": {
        "label": "Stop signs & signals",
        "cause": "Uncontrolled crossings",
        "how": "Adding or upgrading traffic control at uncontrolled crossings gives pedestrians a protected right-of-way.",
        "proxy": "Highest share of fatal/injury pedestrian collisions.",
    },
}


@app.get("/api/solutions")
def solutions(
    type: str = Query(..., pattern="^(rumble_strips|intersection|lighting|stop_signs)$"),
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    top_n: int = 15,
):
    df = _year_params(year_from, year_to)
    df = df.dropna(subset=["LAT_WGS84", "LONG_WGS84"])

    if type == "rumble_strips":
        subset = df[df["FTR_COLLISIONS"] > 0]
    elif type == "intersection":
        subset = df[(df["PEDESTRIAN"] > 0) | (df["BICYCLE"] > 0)]
    elif type == "lighting":
        subset = df[(df["HOUR_BUCKET"] == "Night") & (df["PEDESTRIAN"] > 0)]
    else:  # stop_signs
        subset = df[(df["PEDESTRIAN"] > 0) & (df["SEVERITY_LABEL"].isin(["Fatal", "Injury"]))]

    grouped = subset.groupby("NEIGHBOURHOOD_158").agg(
        lat=("LAT_WGS84", "mean"),
        lon=("LONG_WGS84", "mean"),
        total=("NEIGHBOURHOOD_158", "size"),
    )
    grouped = grouped[grouped.index != "Unknown"].sort_values("total", ascending=False).head(top_n)

    points = [
        {
            "neighbourhood": name,
            "lat": round(float(r.lat), 5),
            "lon": round(float(r.lon), 5),
            "total": int(r.total),
        }
        for name, r in grouped.iterrows()
    ]
    return {"type": type, "definition": SOLUTION_DEFINITIONS[type], "points": points}


@app.get("/api/map")
def map_data(
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    road_user: Optional[str] = None,
    severity: Optional[str] = None,
):
    df = _year_params(year_from, year_to)

    if road_user and road_user.upper() in INVOLVEMENT_COLS:
        df = df[df[road_user.upper()] > 0]
    if severity and severity in SEVERITY_LABELS.values():
        df = df[df["SEVERITY_LABEL"] == severity]

    df = df.dropna(subset=["LAT_WGS84", "LONG_WGS84"])

    grouped = df.groupby("NEIGHBOURHOOD_158").agg(
        lat=("LAT_WGS84", "mean"),
        lon=("LONG_WGS84", "mean"),
        total=("NEIGHBOURHOOD_158", "size"),
        fatal=("FATALITIES", lambda s: int((s > 0).sum())),
        injury=("INJURY_COLLISIONS", lambda s: int((s > 0).sum())),
    )
    grouped = grouped[grouped.index != "Unknown"].sort_values("total", ascending=False)

    points = [
        {
            "neighbourhood": name,
            "lat": round(float(r.lat), 5),
            "lon": round(float(r.lon), 5),
            "total": int(r.total),
            "fatal": int(r.fatal),
            "injury": int(r.injury),
        }
        for name, r in grouped.iterrows()
    ]
    return {"points": points}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
