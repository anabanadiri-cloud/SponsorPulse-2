"""SponsorPulse 2.2 - Private Equity Intelligence Dashboard.

Features:
- Exclude PR and corporate announcements
- Improved Deal Spotlight
- Data-quality review queue
- Clear target-company information
- Historical analytics
- Multiple private equity firm filters

This application reads deals.csv but does not modify it.
"""

from pathlib import Path
import re

import pandas as pd
import plotly.express as px
import streamlit as st


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="SponsorPulse 2.2 | PE Intelligence",
    page_icon="📊",
    layout="wide",
)


# Keep the existing colors and overall design.

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


# ============================================================
# CLASSIFICATION CONSTANTS
# ============================================================

BUY = "BUY / INVESTMENT"
SELL = "SELL / EXIT"
PR = "OTHER / NON-DEAL"
REVIEW = "REVIEW REQUIRED"

DEAL_DIRECTIONS = (BUY, SELL)

NON_DEAL_TYPES = (
    "Personnel / Non-Deal",
    "Fundraising / Capital Close",
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def direction_for_type(transaction_type):

    if transaction_type in (
        "Platform Investment",
        "Add-On Acquisition",
    ):
        return BUY

    if transaction_type == "Full Exit / Sale":
        return SELL

    if transaction_type in NON_DEAL_TYPES:
        return PR

    return REVIEW


def clear_pr_headline(headline):
    """
    Identify announcements that clearly describe
    personnel changes or corporate publicity.

    Avoid automatically treating possible deals as PR.
    """

    title = str(headline).lower()

    # Do not override headlines containing clear deal terms.

    deal_terms = (
        r"\b("
        r"acquir(?:es?|ed|ing)|"
        r"acquisition|"
        r"investment|"
        r"invests?|"
        r"sells?|"
        r"sold|"
        r"exit|"
        r"merger|"
        r"buys?|"
        r"purchase"
        r")\b"
    )

    if re.search(deal_terms, title):
        return False

    pr_patterns = (
        r"\b(appoints?|appointed|appointment|"
        r"promotes?|promoted|hires?|hired)\b",

        r"\b(names?|named)\b.{0,90}"
        r"\b(ceo|cfo|coo|president|director|partner|officer)\b",

        r"\b(new|incoming)\s+"
        r"(ceo|cfo|coo|president|chief executive officer)\b",

        r"\b(chief executive officer|"
        r"chief financial officer|"
        r"chief operating officer)\b",

        r"\b(award|awards|honored|recognition|"
        r"recognizes|featured|interviewed|podcast)\b",
    )

    return any(
        re.search(pattern, title)
        for pattern in pr_patterns
    )


def displayed_transaction_type(row):
    """
    Correct obvious PR classifications
    for display purposes only.

    The original CSV is not changed.
    """

    original = str(
        row.get("transaction_type", "")
    )

    if (
        direction_for_type(original) == REVIEW
        and clear_pr_headline(
            row.get("headline", "")
        )
    ):
        return "Personnel / Non-Deal"

    return original


def normalized_title(value):

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value).lower(),
    ).strip()


def missing(value):

    return str(value).strip().lower() in {
        "",
        "nan",
        "none",
        "n/a",
        "unknown",
        "not stated",
        "not disclosed",
    }


def display_entity(value, direction):
    """
    A non-deal announcement does not need
    an acquisition target.
    """

    if direction == PR:
        return "Not applicable — corporate news"

    if missing(value):

        if direction in DEAL_DIRECTIONS:
            return "Needs source review"

        return "Not identified"

    return str(value)


def quality_issues(row):
    """
    Identify information requiring investigation.

    Do not flag missing acquisition targets
    for ordinary corporate news.
    """

    issues = []

    direction = row["deal_direction"]

    if direction == REVIEW:
        issues.append(
            "Transaction type unclear"
        )

    if direction in DEAL_DIRECTIONS:

        if missing(
            row.get("target_company", "")
        ):
            issues.append(
                "Target not identified"
            )

        if missing(
            row.get("buyer_entity", "")
        ):
            issues.append(
                "Buyer not identified"
            )

    if row["year_label"] == "Unknown Year":
        issues.append(
            "Publication date missing"
        )

    url = str(row.get("url", ""))

    if not url.startswith(
        ("https://", "http://")
    ):
        issues.append(
            "Source URL missing"
        )

    return issues


# ============================================================
# LOAD AND PREPARE DATA
# ============================================================

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

    required_columns = [
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

    for column in required_columns:

        if column not in df.columns:
            df[column] = ""

    # Keep older notebook labels separate from
    # independent transaction verification.

    df["legacy_notebook_label"] = (
        df["is_verified_deal"]
        .str.lower()
        .eq("true")
    )

    df["transaction_type_original"] = (
        df["transaction_type"]
    )

    # Dashboard-only correction of obvious PR.

    df["transaction_type"] = df.apply(
        displayed_transaction_type,
        axis=1,
    )

    df["classification_note"] = df.apply(
        lambda row:
            "Provisional PR categorization from headline "
            "— source review needed"
            if (
                row["transaction_type"]
                != row["transaction_type_original"]
            )
            else "",
        axis=1,
    )

    df["deal_direction"] = (
        df["transaction_type"]
        .apply(direction_for_type)
    )

    # Parse publication dates.

    dates = pd.to_datetime(
        df["announcement_date"],
        errors="coerce",
        format="mixed",
    )

    df["year_label"] = (
        dates.dt.year.apply(
            lambda year:
                str(int(year))
                if pd.notna(year)
                else "Unknown Year"
        )
    )

    # Improve how buyers and targets appear.

    df["target_display"] = df.apply(
        lambda row: display_entity(
            row["target_company"],
            row["deal_direction"],
        ),
        axis=1,
    )

    df["buyer_display"] = df.apply(
        lambda row: display_entity(
            row["buyer_entity"],
            row["deal_direction"],
        ),
        axis=1,
    )

    # Data-quality checks.

    df["quality_issues"] = df.apply(
        lambda row: "; ".join(
            quality_issues(row)
        ),
        axis=1,
    )

    df["verification_note"] = (
        df["review_status"].apply(
            lambda value:
                value.strip()
                if value.strip()
                else "Not independently verified"
        )
    )

    return df


# ============================================================
# CHART STYLING
# ============================================================

def chart_theme(fig, height=320):

    fig.update_layout(
        plot_bgcolor="#10213a",
        paper_bgcolor="#10213a",
        font_color="#e2e8f0",
        height=height,
        margin=dict(
            l=15,
            r=15,
            t=15,
            b=25,
        ),
    )

    return fig


# ============================================================
# INVESTOR RESEARCH QUESTIONS
# ============================================================

def research_questions(row):
    """
    Generate research questions based on the
    recorded transaction type and rationale.

    These questions are not claims about
    financial performance.
    """

    direction = row["deal_direction"]

    rationale = str(
        row.get("strategic_rationale", "")
    ).lower()

    if direction == SELL:

        return [
            "What does this exit suggest about "
            "the sponsor's portfolio strategy?",

            "Are the sale price, holding period, "
            "and realized return publicly disclosed?",

            "What could the new buyer improve "
            "operationally after acquiring the business?",
        ]

    if "geographic" in rationale:

        return [
            "Which additional regions or customer "
            "groups could the company reach?",

            "What distribution, hiring, and integration "
            "costs would expansion require?",

            "Could expansion improve profitability, "
            "or would it primarily increase expenses?",
        ]

    if (
        "product" in rationale
        or "capability" in rationale
    ):

        return [
            "Could the company introduce additional "
            "products or capabilities to existing customers?",

            "Could cross-selling or combined operations "
            "improve profitability?",

            "What operational risks might prevent "
            "successful integration?",
        ]

    return [
        "What investment rationale does the "
        "original announcement actually support?",

        "Are revenue, profit margins, debt, "
        "and purchase price publicly available?",

        "What operational improvements should "
        "an investor investigate during due diligence?",
    ]


# ============================================================
# WEBSITE HEADER
# ============================================================

st.markdown(
    '### 📈 Sponsor'
    '<span style="color:#38bdf8">Pulse</span>'
    ' · DEAL INTELLIGENCE',
    unsafe_allow_html=True,
)

st.title(
    "Private Equity Deal Sourcing "
    "& Operational Intelligence"
)

st.write(
    "Explore public investment announcements, "
    "exits, and relevant company news."
)

st.info(
    "Research prototype. Automated classifications "
    "are **deal candidates**, not independently "
    "verified transactions."
)


# ============================================================
# LOAD DATA
# ============================================================

df_all = load_data()

if df_all.empty:

    st.error(
        "deals.csv is missing or empty. "
        "Keep deals.csv alongside app.py in GitHub."
    )

    st.stop()


# ============================================================
# IDENTIFY REPEATED ANNOUNCEMENTS
# ============================================================

df_all["_title_key"] = (
    df_all["headline"]
    .apply(normalized_title)
)

df_all["_firm_key"] = (
    df_all["source_pe_firm"]
    .str.lower()
    .str.strip()
)

unique_mask = ~df_all.duplicated(
    subset=[
        "_firm_key",
        "_title_key",
    ],
    keep="first",
)

repeat_count = int(
    (~unique_mask).sum()
)


# ============================================================
# SIDEBAR FILTERS
# ============================================================

with st.sidebar:

    st.header(
        "Explore announcements"
    )

    # NEW FEATURE:
    # Exclude clearly identified PR and non-deal news.

    hide_pr = st.checkbox(
        "Exclude PR & non-deal announcements",
        value=True,
        help=(
            "Hides personnel announcements, awards, "
            "and fundraising news. Clear personnel "
            "headlines that were previously unclassified "
            "are provisionally treated as PR. "
            "Ambiguous announcements remain visible."
        ),
    )

    hide_repeats = st.checkbox(
        "Hide repeated announcements",
        value=True,
    )

    sources = sorted(
        df_all["source_pe_firm"]
        .unique()
        .tolist()
    )

    selected_sources = st.multiselect(
        "Private equity firm",
        sources,
        default=sources,
    )

    years = sorted(
        [
            year
            for year in df_all["year_label"].unique()
            if year != "Unknown Year"
        ],
        reverse=True,
    )

    if (
        "Unknown Year"
        in df_all["year_label"].values
    ):
        years.append(
            "Unknown Year"
        )

    selected_years = st.multiselect(
        "Announcement year",
        years,
        default=years,
    )

    directions = sorted(
        df_all["deal_direction"].unique()
    )

    selected_directions = st.multiselect(
        "Deal direction",
        directions,
        default=directions,
    )

    types = sorted(
        df_all["transaction_type"].unique()
    )

    selected_types = st.multiselect(
        "Transaction type",
        types,
        default=types,
    )

    query = st.text_input(
        "Find company, buyer, industry or headline",
        placeholder="E-Z UP, Jones Bearing…",
    )

    legacy_only = st.checkbox(
        "Legacy notebook deal labels only",
        value=False,
        help=(
            "Older notebook labels do not constitute "
            "independent source verification."
        ),
    )


# ============================================================
# APPLY FILTERS
# ============================================================

if hide_repeats:

    base = df_all.loc[
        unique_mask
    ].copy()

else:

    base = df_all.copy()


filtered = base.loc[
    base["source_pe_firm"].isin(
        selected_sources
    )
    & base["year_label"].isin(
        selected_years
    )
    & base["deal_direction"].isin(
        selected_directions
    )
    & base["transaction_type"].isin(
        selected_types
    )
].copy()


# PR EXCLUSION TOGGLE

if hide_pr:

    filtered = filtered[
        filtered["deal_direction"] != PR
    ]


if legacy_only:

    filtered = filtered[
        filtered["legacy_notebook_label"]
    ]


# SEARCH FILTER

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


# ============================================================
# DATASET INFORMATION
# ============================================================

st.caption(
    f"{len(df_all)} raw records · "
    f"{int(unique_mask.sum())} distinct "
    f"firm/headline pairs · "
    f"{repeat_count} repeated entries "
    f"in the source data. "
    + (
        "PR/news excluded from the current view."
        if hide_pr
        else "PR/news included in the current view."
    )
)

provisional_pr_count = int(
    df_all["classification_note"].ne("").sum()
)

if provisional_pr_count:

    st.caption(
        f"{provisional_pr_count} raw announcements "
        "with clear personnel/news headlines are "
        "provisionally treated as PR in the dashboard. "
        "The original CSV is unchanged."
    )


# ============================================================
# DASHBOARD METRICS
# ============================================================

m1, m2, m3, m4, m5 = st.columns(5)

m1.metric(
    "ANNOUNCEMENTS SHOWN",
    len(filtered),
)

m2.metric(
    "PE FIRMS",
    filtered["source_pe_firm"].nunique(),
)

m3.metric(
    "BUY CANDIDATES",
    int(
        (
            filtered["deal_direction"]
            == BUY
        ).sum()
    ),
)

m4.metric(
    "EXIT CANDIDATES",
    int(
        (
            filtered["deal_direction"]
            == SELL
        ).sum()
    ),
)

m5.metric(
    "NEEDS CLASSIFICATION",
    int(
        (
            filtered["deal_direction"]
            == REVIEW
        ).sum()
    ),
)


# ============================================================
# CHART 1: ANNOUNCEMENT CLASSIFICATION
# ============================================================

left, right = st.columns(2)

with left:

    st.subheader(
        "Announcement classification"
    )

    counts = (
        filtered["deal_direction"]
        .value_counts()
        .reindex(
            [
                BUY,
                SELL,
                PR,
                REVIEW,
            ],
            fill_value=0,
        )
    )

    counts = (
        counts[counts > 0]
        .reset_index()
    )

    counts.columns = [
        "Direction",
        "Announcements",
    ]

    if not counts.empty:

        fig = px.bar(
            counts,
            x="Direction",
            y="Announcements",
            color="Direction",
            text="Announcements",
            color_discrete_map={
                BUY: "#10b981",
                SELL: "#fb7185",
                PR: "#64748b",
                REVIEW: "#f59e0b",
            },
        )

        fig.update_layout(
            showlegend=False
        )

        fig.update_yaxes(
            tickformat="d",
            rangemode="tozero",
        )

        st.plotly_chart(
            chart_theme(fig, 335),
            use_container_width=True,
        )

    else:

        st.info(
            "No records match the current filters."
        )


# ============================================================
# CHART 2: RESEARCH COVERAGE
# ============================================================

with right:

    st.subheader(
        "Research coverage by firm"
    )

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

        fig = px.bar(
            counts,
            x="Firm",
            y="Announcements",
            color="Firm",
            text="Announcements",
        )

        fig.update_layout(
            showlegend=False
        )

        fig.update_yaxes(
            tickformat="d",
            rangemode="tozero",
        )

        st.plotly_chart(
            chart_theme(fig, 335),
            use_container_width=True,
        )

    else:

        st.info(
            "No records match the current filters."
        )


# ============================================================
# CHART 3: ANNOUNCEMENTS BY YEAR
# ============================================================

left, right = st.columns(2)

with left:

    st.subheader(
        "Announcements by year"
    )

    by_year = (
        filtered[
            filtered["year_label"] != "Unknown Year"
        ]
        .groupby("year_label")
        .size()
        .reset_index(
            name="Announcements"
        )
        .sort_values(
            "year_label"
        )
    )

    if not by_year.empty:

        fig = px.bar(
            by_year,
            x="year_label",
            y="Announcements",
            text="Announcements",
        )

        fig.update_yaxes(
            tickformat="d",
            rangemode="tozero",
        )

        st.plotly_chart(
            chart_theme(fig),
            use_container_width=True,
        )

    else:

        st.info(
            "No dated records match the filters."
        )


# ============================================================
# CHART 4: INDUSTRY ANALYSIS
# ============================================================

with right:

    st.subheader(
        "Industries in deal candidates"
    )

    candidates = filtered[
        filtered["deal_direction"].isin(
            DEAL_DIRECTIONS
        )
    ]

    industry_counts = (
        candidates["target_industry"]
        .replace(
            "",
            "Unspecified"
        )
        .value_counts()
        .reset_index()
    )

    industry_counts.columns = [
        "Industry",
        "Announcements",
    ]

    if not industry_counts.empty:

        fig = px.pie(
            industry_counts,
            names="Industry",
            values="Announcements",
            hole=0.60,
        )

        st.plotly_chart(
            chart_theme(fig),
            use_container_width=True,
        )

    else:

        st.info(
            "No investment or exit candidates selected."
        )


# ============================================================
# DEAL ACTIVITY REPORT
# ============================================================

st.subheader(
    "Deal activity report"
)

buys = filtered[
    filtered["deal_direction"] == BUY
]

sells = filtered[
    filtered["deal_direction"] == SELL
]

priority = filtered[
    filtered["quality_issues"].ne("")
]

buy_tab, sell_tab, review_tab = st.tabs(
    [
        f"🟢 Investments ({len(buys)})",
        f"🔴 Exits ({len(sells)})",
        f"🟠 Priority review ({len(priority)})",
    ]
)

table_columns = [
    "source_pe_firm",
    "target_display",
    "buyer_display",
    "transaction_type",
    "target_industry",
    "announcement_date",
    "url",
]

link_columns = {
    "url": st.column_config.LinkColumn(
        "Original announcement"
    ),
    "target_display": "Target company",
    "buyer_display": "Buyer / investing entity",
}


with buy_tab:

    st.dataframe(
        buys[table_columns],
        hide_index=True,
        use_container_width=True,
        column_config=link_columns,
    )


with sell_tab:

    st.dataframe(
        sells[table_columns],
        hide_index=True,
        use_container_width=True,
        column_config=link_columns,
    )


with review_tab:

    st.caption(
        "This table highlights unclear transaction types, "
        "missing buyers or targets on deal candidates, "
        "missing dates, and missing source links. "
        "It does not replace manual source verification."
    )

    st.dataframe(
        priority[
            [
                "source_pe_firm",
                "headline",
                "deal_direction",
                "quality_issues",
                "url",
            ]
        ],
        hide_index=True,
        use_container_width=True,
        column_config={
            "url": st.column_config.LinkColumn(
                "Original announcement"
            )
        },
    )


# ============================================================
# IMPROVED DEAL SPOTLIGHT
# ============================================================

st.subheader(
    "🔎 Deal Spotlight — What It May Mean for Investors"
)

spotlights = filtered[
    filtered["deal_direction"].isin(
        DEAL_DIRECTIONS
    )
].reset_index(drop=True)


if spotlights.empty:

    st.info(
        "Select an investment or exit candidate "
        "to explore its potential significance."
    )

else:

    chosen = st.selectbox(
        "Select an announcement",
        options=list(
            range(len(spotlights))
        ),
        format_func=lambda index: (
            f"{spotlights.iloc[index]['source_pe_firm']} "
            f"— {spotlights.iloc[index]['headline']}"
        ),
    )

    record = spotlights.iloc[chosen]

    st.markdown(
        f"#### {record['headline']}"
    )

    # Transaction overview

    c1, c2, c3 = st.columns(3)

    c1.write(
        f"**Sponsor:** {record['source_pe_firm']}"
    )

    c2.write(
        f"**Transaction:** {record['transaction_type']}"
    )

    c3.write(
        "**Publication date:** "
        + (
            record["announcement_date"]
            or "Not identified"
        )
    )

    st.write(
        f"**Target:** {record['target_display']} "
        f"| **Buyer:** {record['buyer_display']}"
    )

    st.write(
        "**Industry (inferred):** "
        + (
            record["target_industry"]
            or "Needs review"
        )
    )

    st.write(
        "**Strategic rationale (automated label):** "
        + (
            record["strategic_rationale"]
            or "Not stated"
        )
    )

    # Supporting evidence

    st.markdown(
        "### What the Source Excerpt Says"
    )

    st.write(
        record["evidence_snippet"]
        or (
            "No excerpt available. "
            "Open the original announcement."
        )
    )

    # Financial analysis

    st.markdown(
        "### Investor Due-Diligence Questions"
    )

    questions = research_questions(
        record
    )

    for question in questions:

        st.write(
            f"• {question}"
        )

    st.caption(
        "These research questions are analytical "
        "hypotheses, not facts about company performance. "
        "SponsorPulse does not establish investment "
        "returns, profit margins, valuations, "
        "or operational alpha."
    )

    # Data quality

    st.caption(
        "Source-check status: "
        + record["verification_note"]
    )

    if record["quality_issues"]:

        st.warning(
            "Data gaps to investigate: "
            + record["quality_issues"]
        )

    # Original article

    if str(record["url"]).startswith(
        ("https://", "http://")
    ):

        st.link_button(
            "Read Original Announcement",
            record["url"],
        )


# ============================================================
# ANNOUNCEMENT EVIDENCE EXPLORER
# ============================================================

st.subheader(
    "Announcement Evidence Explorer"
)

st.caption(
    "A target company is not applicable for ordinary "
    "corporate PR. Missing targets on actual deal "
    "candidates are flagged for review."
)

view_columns = [
    "source_pe_firm",
    "announcement_date",
    "headline",
    "deal_direction",
    "transaction_type",
    "target_display",
    "buyer_display",
    "target_industry",
    "strategic_rationale",
    "quality_issues",
    "classification_note",
    "verification_note",
    "evidence_snippet",
    "url",
]

st.dataframe(
    filtered[view_columns],
    hide_index=True,
    use_container_width=True,
    column_config=link_columns,
)


# ============================================================
# CSV EXPORT
# ============================================================

export_columns = [
    column
    for column in filtered.columns
    if not column.startswith("_")
]

st.download_button(
    "⬇ Export Filtered Research CSV",
    filtered[export_columns]
    .to_csv(index=False)
    .encode("utf-8"),
    file_name="sponsorpulse_filtered.csv",
    mime="text/csv",
)


# ============================================================
# METHODOLOGY AND LIMITATIONS
# ============================================================

with st.expander(
    "Methodology & Limitations"
):

    st.markdown("""
### Announcement Classification

**BUY / INVESTMENT**

Possible platform investments or add-on acquisitions
identified through the announcement text.

**SELL / EXIT**

Possible sales or divestitures.

**OTHER / NON-DEAL**

Personnel updates, awards, fundraising announcements,
and other identifiable corporate news.

**REVIEW REQUIRED**

Announcements that cannot be confidently classified
using the existing automated rules.

### PR Exclusion

The PR checkbox hides identifiable non-deal news.

Some previously unclassified announcements with
clear personnel-related headlines are provisionally
treated as PR by the dashboard.

The original CSV is not modified.

### Missing Target Companies

Corporate PR does not require an acquisition target.

For actual deal candidates, missing buyers and targets
are highlighted for further investigation.

### Verification

Automated classification does not establish that a
transaction has been independently verified.

Investors should review the original announcement
before making decisions.

### Duplicate Records

Repeated firm/headline combinations can be hidden.

Different announcements may still describe the
same underlying transaction.

### Financial Interpretation

Strategic rationales are research hypotheses.

Announcement data alone cannot establish improved
operating performance, realized investment returns,
or successful acquisition integration.

### Data Coverage

SponsorPulse collects a sample of public announcements.

It does not represent the complete private equity market.
""")
