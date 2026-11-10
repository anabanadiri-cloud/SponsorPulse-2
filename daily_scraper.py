"""SponsorPulse 2.3: full-article PE news collection and classification.

This scraper:
1. Collects announcements from Norwest and Tonka Bay.
2. Reads the article body, not just the headline.
3. Extracts explicit acquisition and sale information.
4. Rechecks existing "Review Required" announcements.
5. Preserves existing CSV records and prevents duplicates.

Automatic classifications are NOT independent verification.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd
import requests

from bs4 import BeautifulSoup


LOG = logging.getLogger("sponsorpulse")

HEADERS = {
    "User-Agent": (
        "SponsorPulseAcademicResearch/1.0 "
        "(public news monitoring)"
    )
}


# ============================================================
# SOURCES
# ============================================================

SOURCES = (
    {
        "name": "Norwest Equity Partners",
        "code": "NEP",
        "domain": "nep.com",
        "pages": [
            "https://nep.com/news/"
        ] + [
            f"https://nep.com/news/?current-page={n}"
            for n in range(2, 10)
        ],
    },
    {
        "name": "Tonka Bay Equity Partners",
        "code": "TONKA",
        "domain": "tonkabayequity.com",
        "pages": [
            "https://tonkabayequity.com/news/",
            "https://tonkabayequity.com/news_year_3/",
            "https://tonkabayequity.com/news_year_4/",
            "https://tonkabayequity.com/news_year_5/",
        ],
    },
    {
        "name": "Audax Private Equity",
        "code": "AUDAX",
        "domain": "audaxprivateequity.com",
        "pages": [
            "https://audaxprivateequity.com/news",
        ],
    },
    {
        "name": "Shore Capital Partners",
        "code": "SHORE",
        "domain": "shorecp.com",
        "pages": [
            "https://www.shorecp.com/news",
        ],
    },
)


COLUMNS = [
    "deal_id",
    "source_pe_firm",
    "headline",
    "url",
    "announcement_date",
    "collection_date",
    "is_verified_deal",
    "transaction_type",
    "deal_direction",
    "buyer_entity",
    "target_company",
    "target_industry",
    "strategic_rationale",
    "deal_value_disclosed",
    "evidence_snippet",
    "review_status",
    "data_origin",
]


BUY = "BUY / INVESTMENT"
SELL = "SELL / EXIT"
OTHER = "OTHER / NON-DEAL"
REVIEW = "REVIEW REQUIRED"


DATE_REGEX = re.compile(
    r"\b(?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December)"
    r"\s+\d{1,2},?\s+20\d{2}\b",
    re.I,
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def canonical_url(url):

    parsed = urlparse(str(url).strip())

    domain = parsed.netloc.lower().removeprefix("www.")

    path = "/" + parsed.path.strip("/") + "/"

    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            domain,
            path,
            "",
            "",
            "",
        )
    )


def title_key(value):

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value).lower(),
    ).strip()


def get_html(session, url):

    response = session.get(
        url,
        timeout=25,
    )

    response.raise_for_status()

    return BeautifulSoup(
        response.text,
        "html.parser",
    )


# ============================================================
# DISCOVER ANNOUNCEMENTS
# ============================================================

def discover_links(soup, page_url, domain):

    found = {}

    for anchor in soup.select("a[href]"):

        url = canonical_url(
            urljoin(
                page_url,
                anchor.get("href", ""),
            )
        )

        parsed = urlparse(url)

        parts = (
            parsed.path
            .strip("/")
            .split("/")
        )

        if (
            parsed.netloc != domain
            or len(parts) != 2
            or parts[0].lower() != "news"
        ):
            continue

        headline = anchor.get_text(
            " ",
            strip=True,
        )

        if len(headline) < 18:
            continue

        if headline.lower() in {
            "read more",
            "learn more",
            "view",
            "view more",
            "all news",
            "back to all",
        }:
            continue

        found.setdefault(
            url,
            headline,
        )

    return list(found.items())


# ============================================================
# FULL-ARTICLE READING
# ============================================================

def article_details(soup, fallback_title):
    """
    Read the complete article body.

    The transaction classifier uses the article's
    opening description to avoid confusing old
    acquisitions mentioned in company background
    sections with the newly announced transaction.
    """

    root = (
        soup.find("article")
        or soup.find("main")
        or soup
    )

    # Remove surrounding page elements.

    for node in root.select(
        "script, style, nav, footer, form"
    ):
        node.decompose()

    heading = (
        root.find("h1")
        or soup.find("h1")
    )

    headline = (
        heading.get_text(" ", strip=True)
        if heading
        else fallback_title
    )

    # Collect all substantial paragraphs.

    paragraphs = [
        p.get_text(" ", strip=True)
        for p in root.find_all("p")
    ]

    body = " ".join(
        paragraph
        for paragraph in paragraphs
        if len(paragraph) >= 20
    )[:25000]

    if len(body) < 60:
        body = root.get_text(
            " ",
            strip=True,
        )[:25000]

    # Find publication date.

    date = ""

    for attribute, key in [
        ("property", "article:published_time"),
        ("name", "date"),
        ("name", "publish_date"),
        ("itemprop", "datePublished"),
    ]:

        tag = soup.find(
            "meta",
            attrs={attribute: key},
        )

        if tag and tag.get("content"):
            date = tag["content"].strip()
            break

    if not date:

        tag = (
            root.find("time")
            or soup.find("time")
        )

        if tag:

            date = (
                tag.get("datetime")
                or tag.get_text(" ", strip=True)
            ).strip()

    if not date:

        match = DATE_REGEX.search(
            root.get_text(
                " ",
                strip=True,
            )[:1800]
        )

        if match:
            date = match.group()

    if date:

        parsed = pd.to_datetime(
            date,
            errors="coerce",
            utc=True,
        )

        date = (
            parsed.strftime("%Y-%m-%d")
            if pd.notna(parsed)
            else ""
        )

    return headline, date, body


# ============================================================
# EXTRACT COMPANY NAMES
# ============================================================

def clean_company(value):

    company = re.split(
        r"\s*(?:\(|,|;|\.|\s+from\s+|\s+in\s+an?\s+)\s*",
        value.strip(),
        maxsplit=1,
        flags=re.I,
    )[0]

    return company.strip(
        " –-: "
    )[:120]


# ============================================================
# FIND TRANSACTIONS INSIDE THE ARTICLE
# ============================================================

def lead_event(text, sponsor):
    """
    Look for explicit acquisition or exit language.

    Example:
    'Norwest Equity Partners (NEP), a leading
    investment platform, has acquired MDC
    Interior Solutions.'

    The opening section is prioritized because
    background paragraphs can mention transactions
    that occurred years earlier.
    """

    lead = text[:1800]
    # --------------------------------------------------------
    # SPONSOR INVESTMENTS
    # Recognizes "has made a significant investment in..."
    # --------------------------------------------------------

    investment_pattern = re.compile(
        r"\b(?:Norwest Equity Partners|NEP|"
        r"Tonka Bay Equity Partners|Tonka Bay|"
        r"Audax Private Equity|Audax|"
        r"Shore Capital Partners|Shore Capital)\b"
        r"[^.!?]{0,250}?"
        r"\b(?:has\s+|have\s+)?"
        r"(?:made\s+(?:a|an)\s+"
        r"(?:(?:significant|strategic|growth|"
        r"minority|majority|equity)\s+){0,4}"
        r"investment\s+in|invested\s+in)\s+"
        r"(?P<target>[A-Z][^,;(\n.]{1,110})",
        re.I,
    )

    investment_match = investment_pattern.search(lead)

    if investment_match:

        target = clean_company(
            investment_match.group("target")
        )

        return (
            "Platform Investment",
            BUY,
            sponsor,
            target,
            investment_match.group(0),
        )
    # --------------------------------------------------------
    # 1. SPONSOR ACQUISITIONS
    # --------------------------------------------------------

    pattern = re.compile(
        r"\b(?P<buyer>"
        r"Norwest Equity Partners|"
        r"NEP|"
        r"Tonka Bay Equity Partners|"
        r"Tonka Bay|"
        r"Audax Private Equity|"
        r"Audax|"
        r"Shore Capital Partners|"
        r"Shore Capital"
        r")"
        r"\b[^.!?]{0,200}?"
        r"\b(?:has\s+|have\s+|recently\s+)?"
        r"(?:acquired|acquires|purchased|"
        r"agreed\s+to\s+acquire)\s+"
        r"(?P<target>[A-Z][^.;\n]{2,135})",
        re.I,
    )

    match = pattern.search(lead)

    if match:

        target = clean_company(
            match.group("target")
        )

        return (
            "Platform Investment",
            BUY,
            sponsor,
            target,
            match.group(0),
        )

    # --------------------------------------------------------
    # 2. OPERATING COMPANY ACQUISITIONS
    # --------------------------------------------------------

    pattern = re.compile(
        r"\b(?P<buyer>"
        r"[A-Z][\w&.'-]+"
        r"(?:\s+[A-Z][\w&.'-]+){0,5}"
        r")\s+"
        r"(?:has\s+)?"
        r"(?:acquired|acquires|purchased)\s+"
        r"(?P<target>[A-Z][^.;\n]{2,135})"
    )

    match = pattern.search(lead)

    if match:

        return (
            "Add-On Acquisition",
            BUY,
            match.group("buyer"),
            clean_company(
                match.group("target")
            ),
            match.group(0),
        )

    # --------------------------------------------------------
    # 3. SPONSOR EXITS
    # --------------------------------------------------------

    pattern = re.compile(
        r"\b(?:Norwest Equity Partners|NEP|"
        r"Tonka Bay Equity Partners|Tonka Bay|"
        r"Audax Private Equity|Audax|"
        r"Shore Capital Partners|Shore Capital)\b"
        r"\b[^.!?]{0,120}?"
        r"\b(?:has\s+)?"
        r"(?:sold|divested)\s+"
        r"(?P<target>[A-Z][^.;\n]{2,135})",
        re.I,
    )

    match = pattern.search(lead)

    if match:

        return (
            "Full Exit / Sale",
            SELL,
            "",
            clean_company(
                match.group("target")
            ),
            match.group(0),
        )

    return None


# ============================================================
# CLASSIFICATION
# ============================================================

def classify(headline, body, sponsor):
    """
    Classify using headline AND article body.

    The result is an automated candidate label.
    Human verification is still required.
    """

    title = headline.lower()

    text = headline + " " + body

    tx = "Needs Manual Review"
    direction = REVIEW

    buyer = ""
    target = ""
    evidence = ""

    # --------------------------------------------------------
    # OBVIOUS CORPORATE NEWS
    # --------------------------------------------------------

    if any(
        term in title
        for term in (
            "appoints",
            "appointment",
            "new ceo",
            "named partner",
            "promoted",
            "named chief",
            "award",
            "honored",
            "podcast",
            "interviewed",
            "volunteer",
            "community impact",
            "recogniz",
        )
    ):

        tx = "Personnel / Non-Deal"
        direction = OTHER

    # --------------------------------------------------------
    # FUNDRAISING
    # --------------------------------------------------------

    elif (
        ("fund" in title or "capital" in title)
        and any(
            term in title
            for term in (
                "closes on",
                "fund closing",
                "raised",
                "fundraise",
            )
        )
    ):

        tx = "Fundraising / Capital Close"
        direction = OTHER

    else:

        # Read the actual article's transaction language.

        event = (
            lead_event(body, sponsor)
            if body
            else None
        )

        if event:

            (
                tx,
                direction,
                buyer,
                target,
                evidence,
            ) = event

        # Fallback: recognize explicit transaction headlines.

        elif any(
            term in title
            for term in (
                "sale of",
                "announces sale",
                "sells",
                "sold to",
                "divests",
                "exit from",
            )
        ):

            tx = "Full Exit / Sale"
            direction = SELL

            match = re.search(
                r"\b(?:Sale of|Sells)\s+"
                r"(.+?)\s+to\s+(.+)$",
                headline,
                re.I,
            )

            if match:

                target = clean_company(
                    match.group(1)
                )

                buyer = clean_company(
                    match.group(2)
                )

        elif any(
            term in title
            for term in (
                "acquires",
                "acquire",
                "acquisition of",
                "announces acquisition",
                "merger with",
            )
        ):

            tx = "Add-On Acquisition"
            direction = BUY

            match = re.search(
                r"^(.+?)\s+"
                r"(?:Announces Agreement to\s+)?"
                r"Acquires?\s+(.+)$",
                headline,
                re.I,
            )

            if match:

                buyer = clean_company(
                    match.group(1)
                )

                target = clean_company(
                    match.group(2)
                )

        elif any(
            term in title
            for term in (
                "investment in",
                "invests in",
                "investment into",
                "announces investment",
            )
        ):

            tx = "Platform Investment"
            direction = BUY
            buyer = sponsor

            match = re.search(
                r"\b(?:Investment in|Invests in)"
                r"\s+(.+?)(?:,|$)",
                headline,
                re.I,
            )

            if match:

                target = clean_company(
                    match.group(1)
                )

    # --------------------------------------------------------
    # INDUSTRY EXTRACTION
    # --------------------------------------------------------

    lower_text = text.lower()

    if any(
        word in lower_text
        for word in (
            "it services",
            "managed it",
            "cybersecurity",
            "software",
        )
    ):

        industry = "Business & IT Services"

    elif any(
        word in lower_text
        for word in (
            "wallcoverings",
            "interior finishes",
            "interior solutions",
            "textiles",
            "canopy",
            "produce",
            "food",
        )
    ):

        industry = "Consumer Products & Distribution"

    elif any(
        word in lower_text
        for word in (
            "bearing",
            "locknut",
            "manufacturing",
            "industrial",
            "coatings",
        )
    ):

        industry = "Industrial Manufacturing"

    else:

        industry = "Unknown / Needs Review"

    # --------------------------------------------------------
    # STRATEGIC RATIONALE
    # --------------------------------------------------------

    if any(
        word in lower_text
        for word in (
            "geographic expansion",
            "geographic footprint",
            "expand its footprint",
        )
    ):

        rationale = "Geographic Expansion"

    elif any(
        word in lower_text
        for word in (
            "product line",
            "product range",
            "capabilities",
            "distribution",
            "innovation",
        )
    ):

        rationale = (
            "Product Line & Capability Extension"
        )

    else:

        rationale = "Not stated / Needs Review"

    # --------------------------------------------------------
    # FINANCIAL DISCLOSURE
    # --------------------------------------------------------

    price_disclosed = (
        direction in (BUY, SELL)
        and bool(
            re.search(
                r"\$\s*\d+(?:\.\d+)?\s*"
                r"(?:million|billion|m|bn)\b",
                text,
                re.I,
            )
        )
    )

    # Prefer transaction evidence when available.

    snippet = (
        evidence[:350]
        if evidence
        else (body[:350] if body else headline)
    )

    return {
        "is_verified_deal": False,
        "transaction_type": tx,
        "deal_direction": direction,
        "buyer_entity": buyer,
        "target_company": target,
        "target_industry": industry,
        "strategic_rationale": rationale,
        "deal_value_disclosed": price_disclosed,
        "evidence_snippet": snippet,
        "review_status": (
            "Full-text candidate — "
            "pending manual source verification"
        ),
    }


# ============================================================
# RECHECK EXISTING REVIEW REQUIRED RECORDS
# ============================================================

def review_existing(
    df,
    session,
    limit,
    delay,
):
    """
    Revisit announcements previously marked
    Needs Manual Review.

    Update them when the article contains
    clear evidence of an acquisition, exit,
    or non-deal announcement.

    Do not overwrite records already verified
    by a person.
    """

    changed = 0

    for index, row in df.iterrows():

        if changed >= limit:
            break

        old_type = row.get(
            "transaction_type",
            "",
        )

        if old_type not in (
            "Needs Manual Review",
            "REVIEW REQUIRED",
        ):
            continue

        status = str(
            row.get(
                "review_status",
                "",
            )
        ).lower()

        if status.startswith("verified"):
            continue

        url = row.get("url", "")

        if not url.startswith(
            ("https://", "http://")
        ):
            continue

        domain = (
            urlparse(url)
            .netloc
            .lower()
            .removeprefix("www.")
        )

        allowed_domains = {
            source["domain"]
            for source in SOURCES
        }

        if domain not in allowed_domains:
            continue

        time.sleep(delay)

        try:

            headline, date, body = article_details(
                get_html(session, url),
                row.get("headline", ""),
            )

            if len(body) < 80:
                continue

            result = classify(
                headline,
                body,
                row.get(
                    "source_pe_firm",
                    "",
                ),
            )

            if result["deal_direction"] not in (
                BUY,
                SELL,
                OTHER,
            ):
                continue

            # Do not change an unknown deal to a
            # confirmed-looking classification
            # unless a target was identified.

            if (
                result["deal_direction"] in (
                    BUY,
                    SELL,
                )
                and not result["target_company"]
            ):
                continue

            fields = [
                "transaction_type",
                "deal_direction",
                "buyer_entity",
                "target_company",
                "target_industry",
                "strategic_rationale",
                "deal_value_disclosed",
                "evidence_snippet",
            ]

            for field in fields:

                value = result[field]

                if field == "deal_value_disclosed":
                    value = str(value)

                df.at[index, field] = value

            df.at[
                index,
                "review_status",
            ] = (
                "Reclassified from full text — "
                "pending manual verification"
            )

            if (
                not str(
                    row.get(
                        "announcement_date",
                        "",
                    )
                ).strip()
                and date
            ):

                df.at[
                    index,
                    "announcement_date",
                ] = date

            # Never automatically mark
            # is_verified_deal as True.

            changed += 1

            LOG.info(
                "Reclassified: %s -> %s",
                row.get("headline", ""),
                result["transaction_type"],
            )

        except (
            requests.RequestException,
            ValueError,
        ) as error:

            LOG.warning(
                "Unable to recheck %s: %s",
                url,
                error,
            )

    return changed


# ============================================================
# MAIN UPDATE WORKFLOW
# ============================================================

def update(
    csv_path,
    max_items=80,
    delay=1.0,
    dry_run=False,
    enabled_sources=(),
    max_rechecks=50,
):

    if csv_path.exists():

        existing = pd.read_csv(
            csv_path,
            dtype=str,
            keep_default_na=False,
        )

    else:

        existing = pd.DataFrame(
            columns=COLUMNS
        )

    for column in COLUMNS:

        if column not in existing:
            existing[column] = ""

    existing = existing.copy()

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # --------------------------------------------------------
    # RECHECK OLD UNCLASSIFIED ANNOUNCEMENTS
    # --------------------------------------------------------

    corrected = review_existing(
        existing,
        session,
        max_rechecks,
        delay,
    )

    # --------------------------------------------------------
    # DUPLICATE PROTECTION
    # --------------------------------------------------------

    known_urls = {
        canonical_url(url)
        for url in existing["url"]
        if url.startswith("http")
    }

    known_titles = {
        (
            str(
                row["source_pe_firm"]
            ).lower(),
            title_key(
                row["headline"]
            ),
        )
        for _, row in existing.iterrows()
    }

    collected = []

    index_count = 0

    # --------------------------------------------------------
    # PROCESS EACH PRIVATE EQUITY FIRM
    # --------------------------------------------------------

    for source in SOURCES:

        if (
            enabled_sources
            and source["code"].lower()
            not in enabled_sources
        ):
            continue

        links = {}

        # Read current and historical news indexes.

        for page in source["pages"]:

            try:

                soup = get_html(
                    session,
                    page,
                )

                index_count += 1

                discovered = discover_links(
                    soup,
                    page,
                    source["domain"],
                )

                for url, title in discovered:

                    links.setdefault(
                        url,
                        title,
                    )

            except requests.RequestException as error:

                LOG.warning(
                    "News page unavailable %s: %s",
                    page,
                    error,
                )

            time.sleep(delay)

        added_from_source = 0

        # ----------------------------------------------------
        # OPEN EACH NEW ARTICLE
        # ----------------------------------------------------

        for url, title in links.items():

            if added_from_source >= max_items:
                break

            key = (
                source["name"].lower(),
                title_key(title),
            )

            if (
                url in known_urls
                or key in known_titles
            ):
                continue

            time.sleep(delay)

            try:

                headline, date, body = article_details(
                    get_html(
                        session,
                        url,
                    ),
                    title,
                )

                key = (
                    source["name"].lower(),
                    title_key(headline),
                )

                if (
                    url in known_urls
                    or key in known_titles
                    or len(body) < 80
                ):
                    continue

                record = {
                    "deal_id": (
                        source["code"]
                        + "_"
                        + hashlib.sha256(
                            url.encode()
                        ).hexdigest()[:12]
                    ),
                    "source_pe_firm": (
                        source["name"]
                    ),
                    "headline": headline,
                    "url": url,
                    "announcement_date": date,
                    "collection_date": (
                        datetime.now(
                            timezone.utc
                        ).strftime(
                            "%Y-%m-%d %H:%M:%S UTC"
                        )
                    ),
                    **classify(
                        headline,
                        body,
                        source["name"],
                    ),
                    "data_origin": (
                        "Live full-article scrape — "
                        "pending source review"
                    ),
                }

                collected.append(record)

                known_urls.add(url)

                known_titles.add(key)

                added_from_source += 1

            except requests.RequestException as error:

                LOG.warning(
                    "Article unavailable %s: %s",
                    url,
                    error,
                )

        LOG.info(
            "%s: %s new announcements",
            source["code"],
            added_from_source,
        )

    # --------------------------------------------------------
    # SAVE UPDATED DATA
    # --------------------------------------------------------

    if not index_count and not corrected:

        raise RuntimeError(
            "No news pages reached and no records "
            "changed. Existing CSV preserved."
        )

    if not collected and not corrected:

        LOG.info(
            "No new records or reclassifications. "
            "CSV unchanged."
        )

        return 0

    combined = pd.concat(
        [
            existing,
            pd.DataFrame(collected),
        ],
        ignore_index=True,
    )

    combined = combined.reindex(
        columns=list(
            dict.fromkeys(
                [
                    *existing.columns,
                    *COLUMNS,
                ]
            )
        ),
        fill_value="",
    )

    if dry_run:

        LOG.info(
            "DRY RUN: would reclassify %s "
            "and add %s records.",
            corrected,
            len(collected),
        )

    else:

        csv_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        combined.to_csv(
            csv_path,
            index=False,
        )

        LOG.info(
            "Saved: %s reclassified, "
            "%s new; total %s records.",
            corrected,
            len(collected),
            len(combined),
        )

    return len(collected) + corrected


# ============================================================
# GITHUB ACTIONS ENTRY POINT
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "SponsorPulse full-article "
            "announcement collection"
        )
    )

    parser.add_argument(
        "--csv",
        default="deals.csv",
    )

    parser.add_argument(
        "--max-items",
        type=int,
        default=80,
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
    )

    parser.add_argument(
        "--max-rechecks",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--source",
        choices=[
            "all",
            "nep",
            "tonka",
            "audax",
            "shore",
        ],
        default="all",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:

        update(
            Path(args.csv),
            max_items=max(
                1,
                args.max_items,
            ),
            delay=max(
                0,
                args.delay,
            ),
            dry_run=args.dry_run,
            enabled_sources=(
                ()
                if args.source == "all"
                else (args.source,)
            ),
            max_rechecks=max(
                0,
                args.max_rechecks,
            ),
        )

    except (
        requests.RequestException,
        RuntimeError,
    ) as error:

        LOG.error(
            "Collection failed without "
            "overwriting data: %s",
            error,
        )

        raise SystemExit(1)
