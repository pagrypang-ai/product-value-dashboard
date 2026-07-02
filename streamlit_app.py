from __future__ import annotations

from datetime import date
import os
import re

import altair as alt
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Product Value Matrix", layout="wide")

CURRENT_DATE = pd.Timestamp.today().date()
BRAND_COLOR_PALETTE = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#332288",
    "#88CCEE",
    "#882255",
    "#44AA99",
    "#AA4499",
    "#117733",
    "#DDCC77",
    "#661100",
    "#6699CC",
    "#AA4466",
    "#6A3D9A",
    "#B15928",
    "#1B9E77",
    "#E7298A",
    "#66A61E",
    "#E6AB02",
    "#A6761D",
    "#666666",
    "#E41A1C",
]
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
        "Channel": "Channel",
        "Pickup or not": "Pickup or Not",
        "Number of Reviews": "Number of Reviews",
        "Was Price": "Was Price",
        "Capacity/mAh": "Capacity/mAh",
        "Phone stand": "Phone Stand",
        "LED display": "LED Display",
        "Wireless or Not": "Wireless or Not",
        "Magnetic charging": "Magnetic Charging",
        "Fast charging protocol": "Fast Charging Protocol",
        "USB power (Max)": "USB Power (Max)",
        "URL of Image": "Image URL",
        "Link": "Link",
    }
    return df.rename(columns=rename)


def status_events(row, date_columns):
    events = []
    for col in date_columns:
        value = row.get(col)
        if pd.isna(value) or value == "":
            continue
        text = str(value).lower()
        event_date = pd.to_datetime(col).date()
        if "add" in text:
            events.append((event_date, "available"))
        if "unavailable" in text:
            events.append((event_date, "unavailable"))
    return events


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


def status_on_date(events, query_date):
    status = "unavailable"
    for event_date, event_status in events:
        if event_date <= query_date:
            status = event_status
    return status


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
    if "Channel" not in df.columns:
        df["Channel"] = "Best Buy"
    df["Channel"] = df["Channel"].fillna("Best Buy").astype(str).str.strip()
    df.loc[df["Channel"] == "", "Channel"] = "Best Buy"
    df["Channel Group"] = df["Channel"]
    df["Brand"] = df["Brand"].astype(str).str.strip()
    df["Brand Group"] = df["Brand"].str.replace(r"(?i)^mycharge$", "myCharge", regex=True)
    df["Pickup Group"] = df["Pickup or Not"].astype(str).str.strip().str.title()
    df["Price Num"] = df["Price"].apply(parse_number)
    df["Capacity Num"] = df["Capacity/mAh"].apply(parse_number)
    df["USB Num"] = df["USB Power (Max)"].apply(parse_number)
    df["Capacity Group"] = df["Capacity Num"].apply(lambda x: f"{int(x):,} mAh" if pd.notna(x) else "N/A")
    df["USB Group"] = df["USB Power (Max)"].fillna("N/A").astype(str)
    if "Magnetic Charging" not in df.columns:
        df["Magnetic Charging"] = "N/A"
    df["Magnetic Charging Group"] = df["Magnetic Charging"].fillna("N/A").astype(str).str.strip()
    df.loc[df["Magnetic Charging Group"] == "", "Magnetic Charging Group"] = "N/A"
    df["Image Source"] = df["Image URL"].fillna("").astype(str)

    date_columns = []
    for col in df.columns:
        try:
            pd.to_datetime(col)
            if re.match(r"^\d{4}-\d{2}-\d{2}", str(col)):
                date_columns.append(col)
        except Exception:
            pass

    date_columns = sorted(date_columns, key=lambda col: pd.to_datetime(col).date())
    df["Shelf Events"] = df.apply(lambda row: status_events(row, date_columns), axis=1)
    df["Shelf Periods"] = df.apply(lambda row: status_periods(row, date_columns), axis=1)
    df["Available Now"] = df["Shelf Events"].apply(lambda events: status_on_date(events, CURRENT_DATE) == "available")

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


title_col, mode_col = st.columns([3, 1])
with title_col:
    st.title("Product Value Matrix")
with mode_col:
    display_mode = st.radio(
        "Point Display",
        ["Product Image", "Brand Color"],
        horizontal=True,
    )

sheet_url = ""
try:
    sheet_url = st.secrets.get("GOOGLE_SHEET_CSV_URL", "")
except Exception:
    sheet_url = os.getenv("GOOGLE_SHEET_CSV_URL", "")

uploaded = st.sidebar.file_uploader("Data File", type=["csv", "xlsx"])
df, capacities = load_data(uploaded, sheet_url)

all_dates = []
for events in df["Shelf Events"]:
    for event_date, _ in events:
        all_dates.append(event_date)
min_date = min(all_dates) if all_dates else date(2024, 1, 1)
max_date = max(max(all_dates), CURRENT_DATE) if all_dates else CURRENT_DATE

query_date = st.sidebar.date_input("Query Date", max_date, min_value=min_date, max_value=max_date)
if isinstance(query_date, tuple):
    query_date = query_date[0]
df["Availability on Query Date"] = df["Shelf Events"].apply(lambda events: status_on_date(events, query_date))
channels = st.sidebar.multiselect("Channel", sorted(df["Channel Group"].dropna().unique()), default=sorted(df["Channel Group"].dropna().unique()))
brands = st.sidebar.multiselect("Brand", sorted(df["Brand Group"].dropna().unique()), default=sorted(df["Brand Group"].dropna().unique()))
pickup = st.sidebar.multiselect("Pickup or Not", sorted(df["Pickup Group"].dropna().unique()), default=sorted(df["Pickup Group"].dropna().unique()))
availability = st.sidebar.multiselect("Availability on Query Date", ["available", "unavailable"], default=["available", "unavailable"])
magnetic = st.sidebar.multiselect("Magnetic Charging", sorted(df["Magnetic Charging Group"].dropna().unique()), default=sorted(df["Magnetic Charging Group"].dropna().unique()))
capacity = st.sidebar.multiselect("Capacity", sorted(df["Capacity Group"].dropna().unique()), default=sorted(df["Capacity Group"].dropna().unique()))
usb = st.sidebar.multiselect("USB Power", sorted(df["USB Group"].dropna().unique()), default=sorted(df["USB Group"].dropna().unique()))

mask = (
    df["Channel Group"].isin(channels)
    & df["Brand Group"].isin(brands)
    & df["Pickup Group"].isin(pickup)
    & df["Availability on Query Date"].isin(availability)
    & df["Magnetic Charging Group"].isin(magnetic)
    & df["Capacity Group"].isin(capacity)
    & df["USB Group"].isin(usb)
)
plot_df = df.loc[mask & df["Price Num"].notna() & df["Value Index"].notna() & (df["Image Source"] != "")].copy()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Shown Products", f"{len(plot_df):,}")
col2.metric("Available on Query Date", f"{plot_df['Availability on Query Date'].eq('available').sum():,}")
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

chart_columns = list(dict.fromkeys(["Price Num", "Value Index", "Image Source", "Link", "Brand Group", *DISPLAY_FIELDS]))
chart_df = plot_df[[column for column in chart_columns if column in plot_df.columns]].copy()
for column in chart_df.columns:
    if column not in {"Price Num", "Value Index"}:
        chart_df[column] = chart_df[column].fillna("").astype(str)

x_axis = alt.X("Price Num:Q", title="Price ($)", scale=alt.Scale(zero=False))
y_axis = alt.Y("Value Index:Q", title="Product Value (Capacity + Output Power Max)")

if display_mode == "Product Image":
    chart = (
        alt.Chart(chart_df)
        .mark_image(width=46, height=46)
        .encode(
            x=x_axis,
            y=y_axis,
            url="Image Source:N",
            href="Link:N",
            tooltip=tooltip,
        )
        .properties(height=720)
        .interactive()
    )
else:
    brand_domain = sorted(df["Brand Group"].dropna().astype(str).unique())
    brand_range = [BRAND_COLOR_PALETTE[index % len(BRAND_COLOR_PALETTE)] for index, _ in enumerate(brand_domain)]
    base_chart = alt.Chart(chart_df).encode(x=x_axis, y=y_axis)
    point_chart = base_chart.mark_circle(
        size=170,
        opacity=0.92,
        stroke="#ffffff",
        strokeWidth=1.5,
    ).encode(
        color=alt.Color(
            "Brand Group:N",
            title="Brand",
            scale=alt.Scale(domain=brand_domain, range=brand_range),
        ),
        href="Link:N",
        tooltip=tooltip,
    )
    label_chart = base_chart.mark_text(
        align="center",
        baseline="top",
        dy=12,
        fontSize=10,
        fontWeight="normal",
        color="#1f2933",
        opacity=0.46,
    ).encode(
        text="Brand Group:N",
        href="Link:N",
        tooltip=tooltip,
    )
    chart = (point_chart + label_chart).properties(height=720).interactive()

st.altair_chart(chart, use_container_width=True)
