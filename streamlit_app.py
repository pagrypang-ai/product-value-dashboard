from __future__ import annotations

from datetime import date
import os
import re

import altair as alt
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Product Value Matrix", layout="wide")

CURRENT_DATE = pd.Timestamp.today().date()
DISPLAY_FIELDS = [
    "Brand",
    "Pickup or Not",
    "Sold by",
    "Rating",
    "Number of Reviews",
    "Was Price",
    "Price",
    "Capacity/mAh",
    "Color",
    "Size",
    "Weight",
    "Phone Stand",
    "LED Display",
    "Wired Connect Type",
    "Wireless or Not",
    "Fast Charging Protocol",
    "USB Power (Max)",
    "Warranty",
]


def parse_number(value):
    if pd.isna(value) or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "Pickup or not": "Pickup or Not",
        "Number of Reviews": "Number of Reviews",
        "Was Price": "Was Price",
        "Capacity/mAh": "Capacity/mAh",
        "Phone stand": "Phone Stand",
        "LED display": "LED Display",
        "Wireless or Not": "Wireless or Not",
        "Fast charging protocol": "Fast Charging Protocol",
        "USB power (Max)": "USB Power (Max)",
        "URL of Image": "Image URL",
        "Link": "Link",
    }
    return df.rename(columns=rename)


def status_periods(row, date_columns):
    active_start = None
    periods = []
    for col in date_columns:
        value = row.get(col)
        if pd.isna(value) or value == "":
            continue
        text = str(value).lower()
        event_date = pd.to_datetime(col).date()
        if "add" in text and active_start is None:
            active_start = event_date
        if "unavailable" in text and active_start is not None:
            periods.append((active_start, event_date))
            active_start = None
    if active_start is not None:
        periods.append((active_start, CURRENT_DATE))
    return periods


@st.cache_data(ttl=600)
def load_data(uploaded_file=None, sheet_csv_url=""):
    if uploaded_file is not None:
        if uploaded_file.name.lower().endswith(".xlsx"):
            raw = pd.read_excel(uploaded_file)
        else:
            raw = pd.read_csv(uploaded_file)
    elif sheet_csv_url:
        raw = pd.read_csv(sheet_csv_url)
    else:
        raw = pd.read_csv("data/product_data_sample.csv")

    df = normalize_columns(raw)
    df["Brand"] = df["Brand"].astype(str).str.strip()
    df["Brand Group"] = df["Brand"].str.replace(r"(?i)^mycharge$", "myCharge", regex=True)
    df["Pickup Group"] = df["Pickup or Not"].astype(str).str.strip().str.title()
    df["Price Num"] = df["Price"].apply(parse_number)
    df["Capacity Num"] = df["Capacity/mAh"].apply(parse_number)
    df["USB Num"] = df["USB Power (Max)"].apply(parse_number)
    df["Rating Group"] = df["Rating"].fillna("N/A").astype(str)
    df["Capacity Group"] = df["Capacity Num"].apply(lambda x: f"{int(x):,} mAh" if pd.notna(x) else "N/A")
    df["USB Group"] = df["USB Power (Max)"].fillna("N/A").astype(str)
    df["Image Source"] = df["Image URL"].fillna("").astype(str)

    date_columns = []
    for col in df.columns:
        try:
            pd.to_datetime(col)
            if re.match(r"^\d{4}-\d{2}-\d{2}", str(col)):
                date_columns.append(col)
        except Exception:
            pass

    df["Shelf Periods"] = df.apply(lambda row: status_periods(row, date_columns), axis=1)
    df["Available Now"] = df["Shelf Periods"].apply(lambda periods: bool(periods and periods[-1][1] == CURRENT_DATE))

    capacities = sorted(df["Capacity Num"].dropna().unique())
    rank = {capacity: index + 1 for index, capacity in enumerate(capacities)}
    usb_ranges = df.groupby("Capacity Num")["USB Num"].agg(["min", "max"]).to_dict("index")

    def value_index(row):
        capacity = row["Capacity Num"]
        usb = row["USB Num"]
        if pd.isna(capacity):
            return None
        base = rank[capacity]
        usb_range = usb_ranges.get(capacity, {})
        low, high = usb_range.get("min"), usb_range.get("max")
        if pd.isna(usb) or pd.isna(low) or pd.isna(high) or high == low:
            return base
        return base + ((usb - low) / (high - low)) * 0.8

    df["Value Index"] = df.apply(value_index, axis=1)
    return df, capacities


def overlaps(periods, start, end):
    return any(period_start <= end and period_end >= start for period_start, period_end in periods)


st.title("Product Value Matrix")

sheet_url = ""
try:
    sheet_url = st.secrets.get("GOOGLE_SHEET_CSV_URL", "")
except Exception:
    sheet_url = os.getenv("GOOGLE_SHEET_CSV_URL", "")

uploaded = st.sidebar.file_uploader("Data File", type=["csv", "xlsx"])
df, capacities = load_data(uploaded, sheet_url)

all_dates = []
for periods in df["Shelf Periods"]:
    for start, end in periods:
        all_dates.extend([start, end])
min_date = min(all_dates) if all_dates else date(2024, 1, 1)
max_date = max(all_dates) if all_dates else CURRENT_DATE

start_date, end_date = st.sidebar.date_input("Shelf Date Range", (min_date, max_date), min_value=min_date, max_value=max_date)
brands = st.sidebar.multiselect("Brand", sorted(df["Brand Group"].dropna().unique()), default=sorted(df["Brand Group"].dropna().unique()))
pickup = st.sidebar.multiselect("Pickup or Not", sorted(df["Pickup Group"].dropna().unique()), default=sorted(df["Pickup Group"].dropna().unique()))
ratings = st.sidebar.multiselect("Rating", sorted(df["Rating Group"].dropna().unique()), default=sorted(df["Rating Group"].dropna().unique()))
capacity = st.sidebar.multiselect("Capacity", sorted(df["Capacity Group"].dropna().unique()), default=sorted(df["Capacity Group"].dropna().unique()))
usb = st.sidebar.multiselect("USB Power", sorted(df["USB Group"].dropna().unique()), default=sorted(df["USB Group"].dropna().unique()))

mask = (
    df["Brand Group"].isin(brands)
    & df["Pickup Group"].isin(pickup)
    & df["Rating Group"].isin(ratings)
    & df["Capacity Group"].isin(capacity)
    & df["USB Group"].isin(usb)
    & df["Shelf Periods"].apply(lambda periods: overlaps(periods, start_date, end_date))
)
plot_df = df.loc[mask & df["Price Num"].notna() & df["Value Index"].notna() & (df["Image Source"] != "")].copy()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Shown Products", f"{len(plot_df):,}")
col2.metric("Available Now", f"{plot_df['Available Now'].sum():,}")
col3.metric("Median Price", "N/A" if plot_df.empty else f"${plot_df['Price Num'].median():,.2f}")
col4.metric(
    "Capacity Range",
    "N/A" if plot_df.empty else f"{int(plot_df['Capacity Num'].min()):,}-{int(plot_df['Capacity Num'].max()):,} mAh",
)

tooltip = [
    alt.Tooltip("Brand:N", title="Brand"),
    alt.Tooltip("Pickup or Not:N", title="Pickup or Not"),
    alt.Tooltip("Sold by:N", title="Sold by"),
    alt.Tooltip("Rating:N", title="Rating"),
    alt.Tooltip("Number of Reviews:N", title="Number of Reviews"),
    alt.Tooltip("Was Price:N", title="Was Price"),
    alt.Tooltip("Price:N", title="Price"),
    alt.Tooltip("Capacity/mAh:N", title="Capacity/mAh"),
    alt.Tooltip("Color:N", title="Color"),
    alt.Tooltip("Size:N", title="Size"),
    alt.Tooltip("Weight:N", title="Weight"),
    alt.Tooltip("Phone Stand:N", title="Phone Stand"),
    alt.Tooltip("LED Display:N", title="LED Display"),
    alt.Tooltip("Wired Connect Type:N", title="Wired Connect Type"),
    alt.Tooltip("Wireless or Not:N", title="Wireless or Not"),
    alt.Tooltip("Fast Charging Protocol:N", title="Fast Charging Protocol"),
    alt.Tooltip("USB Power (Max):N", title="USB Power (Max)"),
    alt.Tooltip("Warranty:N", title="Warranty"),
]

chart = (
    alt.Chart(plot_df)
    .mark_image(width=46, height=46)
    .encode(
        x=alt.X("Price Num:Q", title="Price ($)", scale=alt.Scale(zero=False)),
        y=alt.Y("Value Index:Q", title="Product Value"),
        url="Image Source:N",
        href="Link:N",
        tooltip=tooltip,
    )
    .properties(height=720)
    .interactive()
)

st.altair_chart(chart, use_container_width=True)
