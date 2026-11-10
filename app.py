"""SponsorPulse 2.1 - Private Equity Intelligence Dashboard."""

from pathlib import Path
import re

import pandas as pd
import plotly.express as px
import streamlit as st


# -------------------------------------------------
# PAGE SETUP
# -------------------------------------------------

st.set_page_config(
    page_title="SponsorPulse 2.1 | PE Intelligence",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
.stApp {
    background: #071321;
    color: #eef5ff;
}

.block-container {
    padding-top: 1.6rem;
    max-width: 1350px;
}

h1, h2, h3 {
    color: #f3f7ff !important;
}

[data-testid="stMetric"] {
    background: #10213a;
    border: 1px solid #203b5b;
    border-radius: 14px;
    padding: 18px;
}

[data-testid="stMetricLabel"] {
    color: #b4c4d8;
}

[data-testid="stMetricValue"] {
    color: #3ce0b6;
}

section[data-testid="stSidebar"] {
    background: #0c1b30;
}
</style>
""", unsafe_allow_html=True)


# -------------------------------------------------
# LOAD DATA
# -------------------------------------------------

@st.cache_data(ttl=300)
def load_data():

    path = Path(__file__).parent / "deals.csv"

    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )

    required = [
        "source_pe_firm",
        "headline",
        "url",
        "announcement_date",
        "is_verified_deal",
        "transaction_type",
        "buyer_entity",
        "target_company",
        "target_industry",
        "strategic_rationale",
        "evidence_snippet",
        "review_status",
    ]

    for column in required:
        if column not in df:
            df[column] = ""

    df["is_verified_deal"] = (
        df["is_verified_deal"]
        .str.lower()
        .eq("true")
    )

    def direction(transaction_type):

        if transaction_type in (
            "Platform Investment",
            "Add-On Acquisition",
        ):
            return "BUY / INVESTMENT"

        if transaction_type == "Full Exit / Sale":
            return "SELL / EXIT"

        if transaction_type in (
            "Personnel / Non-Deal",
            "Fundraising / Capital Close",
        ):
            return "OTHER / NON-DEAL"

        return "REVIEW REQUIRED"

    df["deal_direction"] = (
        df["transaction_type"].apply(direction)
    )

    dates = pd.to_datetime(
        df["announcement_date"],
        errors="coerce",
        format="mixed",
    )

    df["year_label"] = dates.dt.year.apply(
        lambda year: (
            str(int(year))
            if pd.notna(year)
            else "Unknown Year"
        )
    )

    return df


def normalized_title(title):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(title).lower(),
    ).strip()


df_all = load_data()


# -------------------------------------------------
# HEADER
# -------------------------------------------------

st.markdown(
    '### 📈 Sponsor'
    '<span style="color:#38bdf8">Pulse</span>'
    ' · DEAL INTELLIGENCE',
    unsafe_allow_html=True,
)

st.title(
    "Private Equity Deal Sourcing & Operational Intelligence"
)

st.write(
    "Track investments, exits, and corporate news "
    "from public private equity announcements."
)

st.info(
    "Source-linked research prototype. "
    "Automatically classified announcements are "
    "candidates, not independently verified deals."
)

if df_all.empty:
    st.error(
        "No deals.csv found. Keep deals.csv "
        "in the same repository as app.py."
    )
    st.stop()


# -------------------------------------------------
# DUPLICATE HANDLING
# -------------------------------------------------

df = df_all.copy()

df["_title_key"] = (
    df["headline"].apply(normalized_title)
)

df["_source_key"] = (
    df["source_pe_firm"]
    .str.lower()
    .str.strip()
)

unique_mask = ~df.duplicated(
    subset=["_source_key", "_title_key"],
    keep="first",
)

repeat_count = int(
    (~unique_mask).sum()
)


# -------------------------------------------------
# SIDEBAR FILTERS
# -------------------------------------------------

with st.sidebar:

    st.header("Explore announcements")

    hide_repeats = st.checkbox(
        "Hide repeated announcements",
        value=True,
    )

    sources = sorted(
        df["source_pe_firm"].unique().tolist()
    )

    selected_sources = st.multiselect(
        "Private equity firm",
        sources,
        default=sources,
    )

    years = sorted(
        [
            year
            for year in df["year_label"].unique()
            if year != "Unknown Year"
        ],
        reverse=True,
    )

    if "Unknown Year" in df["year_label"].values:
        years.append("Unknown Year")

    selected_years = st.multiselect(
        "Announcement year",
        years,
        default=years,
    )

    directions = sorted(
        df["deal_direction"].unique()
    )

    selected_directions = st.multiselect(
        "Deal direction",
        directions,
        default=directions,
    )

    types = sorted(
        df["transaction_type"].unique()
    )

    selected_types = st.multiselect(
        "Transaction type",
        types,
        default=types,
    )

    query = st.text_input(
        "Find company, buyer, industry or headline",
        placeholder="Jones Bearing, Technology...",
    )

    legacy_only = st.checkbox(
        "Legacy notebook deal labels only",
        value=False,
        help=(
            "Older cached records may be labeled verified, "
            "but those labels are not proof of independent "
            "source verification."
        ),
    )


# -------------------------------------------------
# APPLY FILTERS
# -------------------------------------------------

if hide_repeats:
    df = df.loc[unique_mask].copy()

filtered = df.loc[
    df["source_pe_firm"].isin(selected_sources)
    & df["year_label"].isin(selected_years)
    & df["deal_direction"].isin(selected_directions)
    & df["transaction_type"].isin(selected_types)
].copy()

if legacy_only:
    filtered = filtered[
        filtered["is_verified_deal"]
    ]

if query.strip():

    searchable = (
        filtered[
            [
                "headline",
                "target_company",
                "buyer_entity",
                "target_industry",
                "source_pe_firm",
            ]
        ]
        .astype(str)
        .agg(" ".join, axis=1)
    )

    filtered = filtered[
        searchable.str.contains(
            query.strip(),
            case=False,
            regex=False,
        )
    ]


# -------------------------------------------------
# DATA QUALITY NOTICE
# -------------------------------------------------

if repeat_count:

    st.caption(
        f"Dataset contains {len(df_all)} raw records "
        f"and {int(unique_mask.sum())} distinct "
        f"firm/headline pairs. "
        f"{repeat_count} repeated records "
        f"{'hidden' if hide_repeats else 'shown'}."
    )


# -------------------------------------------------
# DASHBOARD METRICS
# -------------------------------------------------

m1, m2, m3, m4, m5 = st.columns(5)

m1.metric(
    "ANNOUNCEMENTS",
    len(filtered),
)

m2.metric(
    "PE FIRMS",
    filtered["source_pe_firm"].nunique(),
)

m3.metric(
    "BUY / INVESTMENT",
    int(
        (
            filtered["deal_direction"]
            == "BUY / INVESTMENT"
        ).sum()
    ),
)

m4.metric(
    "SELL / EXIT",
    int(
        (
            filtered["deal_direction"]
            == "SELL / EXIT"
        ).sum()
    ),
)

m5.metric(
    "OTHER / NON-DEAL",
    int(
        (
            filtered["deal_direction"]
            == "OTHER / NON-DEAL"
        ).sum()
    ),
)


# -------------------------------------------------
# CHART 1: ANNOUNCEMENT CLASSIFICATION
# -------------------------------------------------

left, right = st.columns(2)

with left:

    st.subheader("Announcement classification")

    counts = (
        filtered["deal_direction"]
        .value_counts()
        .reindex(
            [
                "BUY / INVESTMENT",
                "SELL / EXIT",
                "OTHER / NON-DEAL",
                "REVIEW REQUIRED",
            ],
            fill_value=0,
        )
    )

    counts = counts[
        counts > 0
    ].reset_index()

    counts.columns = [
        "Direction",
        "Announcements",
    ]

    if not counts.empty:

        chart = px.bar(
            counts,
            x="Direction",
            y="Announcements",
            color="Direction",
            text="Announcements",
            color_discrete_map={
                "BUY / INVESTMENT": "#10b981",
                "SELL / EXIT": "#fb7185",
                "OTHER / NON-DEAL": "#64748b",
                "REVIEW REQUIRED": "#f59e0b",
            },
        )

        chart.update_layout(
            showlegend=False,
            plot_bgcolor="#10213a",
            paper_bgcolor="#10213a",
            font_color="#e2e8f0",
            height=335,
        )

        chart.update_yaxes(dtick=1)

        st.plotly_chart(
            chart,
            use_container_width=True,
        )

    else:
        st.info("No matching records.")


# -------------------------------------------------
# CHART 2: PRIVATE EQUITY FIRMS
# -------------------------------------------------

with right:

    st.subheader("Research coverage by firm")

    counts = (
        filtered["source_pe_firm"]
        .value_counts()
        .reset_index()
    )

    counts.columns = [
        "Firm",
        "Announcements",
    ]

    if not counts.empty:

        chart = px.bar(
            counts,
            x="Firm",
            y="Announcements",
            text="Announcements",
            color="Firm",
        )

        chart.update_layout(
            showlegend=False,
            plot_bgcolor="#10213a",
            paper_bgcolor="#10213a",
            font_color="#e2e8f0",
            height=335,
        )

        chart.update_yaxes(dtick=1)

        st.plotly_chart(
            chart,
            use_container_width=True,
        )

    else:
        st.info("No matching records.")


# -------------------------------------------------
# CHART 3: ANNOUNCEMENTS BY YEAR
# -------------------------------------------------

left, right = st.columns(2)

with left:

    st.subheader("Announcements by year")

    subset = filtered[
        filtered["year_label"] != "Unknown Year"
    ]

    by_year = (
        subset.groupby("year_label")
        .size()
        .reset_index(name="Announcements")
    )

    if not by_year.empty:

        chart = px.bar(
            by_year.sort_values("year_label"),
            x="year_label",
            y="Announcements",
            text="Announcements",
        )

        chart.update_layout(
            plot_bgcolor="#10213a",
            paper_bgcolor="#10213a",
            font_color="#e2e8f0",
            height=310,
        )

        chart.update_yaxes(dtick=1)

        st.plotly_chart(
            chart,
            use_container_width=True,
        )

    else:
        st.info(
            "No announcement dates available."
        )


# -------------------------------------------------
# CHART 4: INDUSTRY BREAKDOWN
# -------------------------------------------------

with right:

    st.subheader("Industries in deal candidates")

    candidates = filtered[
        filtered["deal_direction"].isin(
            [
                "BUY / INVESTMENT",
                "SELL / EXIT",
            ]
        )
    ]

    industry_counts = (
        candidates["target_industry"]
        .replace("", "Unspecified")
        .value_counts()
        .reset_index()
    )

    industry_counts.columns = [
        "Industry",
        "Announcements",
    ]

    if not industry_counts.empty:

        chart = px.pie(
            industry_counts,
            names="Industry",
            values="Announcements",
            hole=0.60,
        )

        chart.update_layout(
            paper_bgcolor="#10213a",
            font_color="#e2e8f0",
            height=310,
        )

        st.plotly_chart(
            chart,
            use_container_width=True,
        )

    else:
        st.info(
            "No investment or exit candidates selected."
        )


# -------------------------------------------------
# INVESTMENTS AND EXITS
# -------------------------------------------------

buys = filtered[
    filtered["deal_direction"]
    == "BUY / INVESTMENT"
]

sells = filtered[
    filtered["deal_direction"]
    == "SELL / EXIT"
]

st.subheader("Deal activity report")

buy_tab, sell_tab = st.tabs([
    f"🟢 Investments ({len(buys)})",
    f"🔴 Exits ({len(sells)})",
])

table_cols = [
    "source_pe_firm",
    "target_company",
    "buyer_entity",
    "transaction_type",
    "target_industry",
    "announcement_date",
    "url",
]

with buy_tab:

    st.dataframe(
        buys[table_cols],
        hide_index=True,
        use_container_width=True,
    )

with sell_tab:

    st.dataframe(
        sells[table_cols],
        hide_index=True,
        use_container_width=True,
    )


# -------------------------------------------------
# DEAL SPOTLIGHT
# -------------------------------------------------

st.subheader(
    "Deal spotlight: why it might matter"
)

spotlights = filtered[
    filtered["deal_direction"].isin(
        [
            "BUY / INVESTMENT",
            "SELL / EXIT",
        ]
    )
]

if not spotlights.empty:

    labels = [
        f"{row['source_pe_firm']} — {row['headline']}"
        for _, row in spotlights.iterrows()
    ]

    chosen = st.selectbox(
        "Choose an announcement",
        list(range(len(labels))),
        format_func=lambda index: labels[index],
        label_visibility="collapsed",
    )

    row = spotlights.iloc[chosen]

    st.markdown(
        f"**{row['headline']}**"
    )

    st.write(
        f"**Firm:** {row['source_pe_firm']} "
        f"| **Type:** {row['transaction_type']}"
    )

    st.write(
        f"**Buyer:** "
        f"{row['buyer_entity'] or 'Unclear'} "
        f"| **Target:** "
        f"{row['target_company'] or 'Unclear'}"
    )

    st.write(
        f"**Potential strategic rationale:** "
        f"{row['strategic_rationale'] or 'Not stated'}"
    )

    st.caption(
        "Strategic rationale is a screening hypothesis, "
        "not proof that a transaction created value."
    )

    if row["url"]:

        st.link_button(
            "Read original source",
            row["url"],
        )

else:

    st.info(
        "Select an investment or exit "
        "to see its research spotlight."
    )


# -------------------------------------------------
# ANNOUNCEMENT EVIDENCE EXPLORER
# -------------------------------------------------

st.subheader("Announcement evidence explorer")

view_cols = [
    "source_pe_firm",
    "announcement_date",
    "headline",
    "deal_direction",
    "transaction_type",
    "target_company",
    "buyer_entity",
    "target_industry",
    "strategic_rationale",
    "review_status",
    "evidence_snippet",
    "url",
]

st.dataframe(
    filtered[view_cols],
    hide_index=True,
    use_container_width=True,
    column_config={
        "url": st.column_config.LinkColumn(
            "Original announcement"
        )
    },
)


# -------------------------------------------------
# CSV EXPORT
# -------------------------------------------------

export_cols = [
    column
    for column in filtered.columns
    if not column.startswith("_")
]

st.download_button(
    "⬇ Export filtered CSV",
    filtered[export_cols]
    .to_csv(index=False)
    .encode("utf-8"),
    file_name="sponsorpulse_filtered.csv",
    mime="text/csv",
)


# -------------------------------------------------
# METHODOLOGY
# -------------------------------------------------

with st.expander(
    "Methodology & limitations"
):

    st.markdown("""
**Investment candidates**

Announcements automatically identified
as acquisitions or investments.

**Exit candidates**

Announcements describing sales or divestitures.

**Other news**

Personnel announcements, fund closings,
and unrelated corporate news.

**Review required**

Announcements that cannot be confidently
classified by the existing rules.

**Duplicate handling**

Repeated firm/headline pairs can be hidden.
The original CSV remains unchanged.

**Data limitations**

- New records are not independently verified.
- Announcement dates are not necessarily closing dates.
- Transaction values may be undisclosed.
- Industry classifications may require manual correction.
- Public announcements do not represent every PE deal.
- Operational alpha cannot be proven from
  deal announcements alone.
""")
