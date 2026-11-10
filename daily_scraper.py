Sources:
- Norwest Equity Partners (9 news pages)
- Tonka Bay Equity Partners (recent news and 2022-2024 archives)

New announcements are automatically classified, NOT independently verified.
Existing CSV records are preserved.
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
    "User-Agent": "SponsorPulseAcademicResearch/1.0 (public news monitoring)"
}

SOURCES = (
    {
        "name": "Norwest Equity Partners",
        "code": "NEP",
        "domain": "nep.com",
        "pages": ["https://nep.com/news/"]
        + [
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

DATE_REGEX = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+20\d{2}\b",
    re.I,
)


def canonical_url(url: str) -> str:
    """Standardize URLs to help prevent duplicate records."""
    parsed = urlparse(str(url).strip())
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = "/" + parsed.path.strip("/") + "/"

    return urlunparse(
        (parsed.scheme.lower() or "https", netloc, path, "", "", "")
    )


def normalized_title(title: str) -> str:
    """Normalize headlines for duplicate detection."""
    return re.sub(
        r"[^a-z0-9]+", " ", str(title).lower()
    ).strip()


def get_html(
    session: requests.Session,
    url: str
) -> BeautifulSoup:

    response = session.get(url, timeout=25)
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


def discover_links(
    soup: BeautifulSoup,
    page_url: str,
    domain: str
) -> list[tuple[str, str]]:

    """Find article links on a source's news page."""
    found = {}

    for anchor in soup.select("a[href]"):

        link = canonical_url(
            urljoin(page_url, anchor.get("href", ""))
        )

        parsed = urlparse(link)

        if parsed.netloc != domain:
            continue

        components = parsed.path.strip("/").split("/")

        if (
            len(components) != 2
            or components[0].lower() != "news"
        ):
            continue

        headline = anchor.get_text(" ", strip=True)

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

        found.setdefault(link, headline)

    return list(found.items())


def article_details(
    soup: BeautifulSoup,
    fallback_title: str
) -> tuple[str, str, str]:

    """Extract headline, announcement date and article text."""

    main = (
        soup.find("article")
        or soup.find("main")
        or soup
    )

    heading = (
        main.find("h1")
        or main.find("h2")
        or soup.find("h1")
        or soup.find("h2")
    )

    title = (
        heading.get_text(" ", strip=True)
        if heading
        else fallback_title
    )

    paragraphs = [
        p.get_text(" ", strip=True)
        for p in main.find_all("p")
    ]

    body = " ".join(
        p for p in paragraphs if len(p) >= 25
    )[:15000]

    if len(body) < 60:
        body = main.get_text(" ", strip=True)[:15000]

    date = ""

    for attr, key in [
        ("property", "article:published_time"),
        ("name", "date"),
        ("name", "publish_date"),
        ("itemprop", "datePublished"),
    ]:

        tag = soup.find("meta", attrs={attr: key})

        if tag and tag.get("content"):
            date = tag["content"].strip()
            break

    if not date:
        tag = main.find("time") or soup.find("time")

        if tag:
            date = (
                tag.get("datetime")
                or tag.get_text(" ", strip=True)
            ).strip()

    if not date:
        match = DATE_REGEX.search(
            main.get_text(" ", strip=True)[:1300]
        )

        if match:
            date = match.group(0)

    if date:
        parsed = pd.to_datetime(
            date,
            errors="coerce",
            utc=True
        )

        date = (
            parsed.strftime("%Y-%m-%d")
            if pd.notna(parsed)
            else ""
        )

    return title, date, body


def classify(
    headline: str,
    body: str,
    sponsor: str
) -> dict:

    """Classify announcements conservatively.

    These are candidate classifications, not verified deals.
    """

    title = headline.lower()
    text = (headline + " " + body).lower()

    if any(
        x in title
        for x in (
            "appoints",
            "appointed",
            "appointment",
            "named partner",
            "named a",
            "promoted",
            "promotes",
            "joins tonka",
            "award",
            "honored",
            "podcast",
            "featured",
            "interviewed",
            "volunteer",
            "community impact",
            "recogniz",
        )
    ):
        tx = "Personnel / Non-Deal"
        direction = "OTHER / NON-DEAL"

    elif (
        ("fund" in title or "capital" in title)
        and any(
            x in title
            for x in (
                "closes",
                "closing",
                "raised",
                "fundraise",
            )
        )
    ):
        tx = "Fundraising / Capital Close"
        direction = "OTHER / NON-DEAL"

    elif any(
        x in title
        for x in (
            "sale of",
            "announces sale",
            "sells",
            "sold to",
            "divests",
            "exit from",
        )
    ):
        tx = "Full Exit / Sale"
        direction = "SELL / EXIT"

    elif any(
        x in title
        for x in (
            "acquires",
            "acquire",
            "acquisition of",
            "announces acquisition",
            "merger with",
        )
    ):
        tx = "Add-On Acquisition"
        direction = "BUY / INVESTMENT"

    elif any(
        x in title
        for x in (
            "investment in",
            "invests in",
            "investment into",
            "announces investment",
        )
    ):
        tx = "Platform Investment"
        direction = "BUY / INVESTMENT"

    else:
        tx = "Needs Manual Review"
        direction = "REVIEW REQUIRED"

    buyer = ""
    target = ""

    if tx == "Full Exit / Sale":

        match = re.search(
            r"\bSale of\s+(.+?)\s+to\s+(.+)$",
            headline,
            re.I,
        )

        if match:
            target = match.group(1).strip()
            buyer = match.group(2).strip()

        else:
            match = re.search(
                r"\bSells\s+(.+?)\s+to\s+(.+)$",
                headline,
                re.I,
            )

            if match:
                target = match.group(1).strip()
                buyer = match.group(2).strip()

    elif tx == "Platform Investment":

        match = re.search(
            r"\b(?:Investment in|Invests in|Investment into)"
            r"\s+(.+?)(?:[,;]|$)",
            headline,
            re.I,
        )

        if match:
            target = match.group(1).strip()
            buyer = sponsor

    elif tx == "Add-On Acquisition":

        match = re.search(
            r"^(.+?)\s+(?:Announces\s+)?"
            r"(?:Agreement to\s+)?Acquires?\s+(.+)$",
            headline,
            re.I,
        )

        if match:
            buyer = match.group(1).strip()
            target = match.group(2).strip()

        else:
            match = re.search(
                r"^(.+?)\s+Announces Acquisition of\s+(.+)$",
                headline,
                re.I,
            )

            if match:
                buyer = match.group(1).strip()
                target = match.group(2).strip()

    # Identify possible target industry

    if any(
        x in text
        for x in (
            "managed it",
            "it services",
            "cybersecurity",
            "software",
            "technology",
        )
    ):
        industry = "Business & IT Services"

    elif any(
        x in text
        for x in (
            "canopy",
            "wallcoverings",
            "textiles",
            "produce",
            "food",
        )
    ):
        industry = "Consumer Products & Distribution"

    elif any(
        x in text
        for x in (
            "manufacturing",
            "industrial",
            "bearing",
            "locknut",
            "coatings",
        )
    ):
        industry = "Industrial Manufacturing"

    else:
        industry = "Unknown / Needs Review"

    # Identify possible strategic rationale

    if any(
        x in text
        for x in (
            "geographic expansion",
            "geographic footprint",
            "expand its footprint",
            "expands its footprint",
            "broadening its reach",
        )
    ):
        rationale = "Geographic Expansion"

    elif any(
        x in text
        for x in (
            "product offering",
            "product range",
            "product line",
            "capabilities",
            "capability",
            "innovation",
            "distribution",
            "cross-sell",
        )
    ):
        rationale = "Product Line & Capability Extension"

    else:
        rationale = "Not stated / Needs Review"

    # Detect whether a deal value appears in the text.
    # It must still be checked manually.

    price = bool(
        re.search(
            r"\$\s*\d+(?:\.\d+)?\s*"
            r"(?:million|billion|m|bn)\b",
            text,
            re.I,
        )
    )

    if direction not in (
        "BUY / INVESTMENT",
        "SELL / EXIT",
    ):
        price = False

    return {
        "is_verified_deal": False,
        "transaction_type": tx,
        "deal_direction": direction,
        "buyer_entity": buyer,
        "target_company": target,
        "target_industry": industry,
        "strategic_rationale": rationale,
        "deal_value_disclosed": price,
        "evidence_snippet": (
            body[:300] if body else headline
        ),
        "review_status": "Pending manual verification",
    }


def update(
    csv_path: Path,
    max_items: int = 80,
    delay: float = 1.0,
    dry_run: bool = False,
    enabled_sources: tuple[str, ...] = (),
) -> int:

    """Collect new announcements without deleting old records."""

    if csv_path.exists():
        existing = pd.read_csv(
            csv_path,
            dtype=str,
            keep_default_na=False,
        )
    else:
        existing = pd.DataFrame(columns=COLUMNS)

    known_urls = {
        canonical_url(url)
        for url in existing.get(
            "url",
            pd.Series(dtype=str)
        )
        if str(url).strip().startswith("http")
    }

    known_titles = {
        (
            str(row.get("source_pe_firm", "")).lower(),
            normalized_title(row.get("headline", "")),
        )
        for _, row in existing.iterrows()
    }

    collected = []
    reachable_index_pages = 0

    session = requests.Session()
    session.headers.update(HEADERS)

    for source in SOURCES:

        if (
            enabled_sources
            and source["code"].lower() not in enabled_sources
        ):
            continue

        candidate_links = {}

        # Visit current and historical news pages

        for page in source["pages"]:

            try:
                soup = get_html(session, page)
                reachable_index_pages += 1

                links = discover_links(
                    soup,
                    page,
                    source["domain"]
                )

                for url, title in links:
                    candidate_links.setdefault(url, title)

                LOG.info(
                    "%s index: %s candidate articles",
                    source["code"],
                    len(candidate_links),
                )

            except requests.RequestException as error:
                LOG.warning(
                    "Cannot access %s: %s",
                    page,
                    error,
                )

            time.sleep(delay)

        queued = 0

        # Visit individual articles

        for url, title in candidate_links.items():

            if queued >= max_items:
                break

            key = (
                source["name"].lower(),
                normalized_title(title),
            )

            if url in known_urls or key in known_titles:
                continue

            queued += 1
            time.sleep(delay)

            try:
                article = get_html(session, url)

                headline, date, body = article_details(
                    article,
                    title,
                )

                key = (
                    source["name"].lower(),
                    normalized_title(headline),
                )

                if (
                    url in known_urls
                    or key in known_titles
                ):
                    continue

                if len(body) < 60:
                    LOG.warning(
                        "Article has insufficient text: %s",
                        url,
                    )
                    continue

                record = {
                    "deal_id": (
                        source["code"]
                        + "_"
                        + hashlib.sha256(
                            url.encode()
                        ).hexdigest()[:12]
                    ),
                    "source_pe_firm": source["name"],
                    "headline": headline,
                    "url": url,
                    "announcement_date": date,
                    "collection_date": (
                        datetime.now(timezone.utc)
                        .strftime("%Y-%m-%d %H:%M:%S UTC")
                    ),
                    **classify(
                        headline,
                        body,
                        source["name"],
                    ),
                    "data_origin": (
                        "Live article scrape - pending review"
                    ),
                }

                collected.append(record)
                known_urls.add(url)
                known_titles.add(key)

            except requests.RequestException as error:
                LOG.warning(
                    "Cannot access article %s: %s",
                    url,
                    error,
                )

    if reachable_index_pages == 0:
        raise RuntimeError(
            "No source news pages could be reached. "
            "Existing CSV was not changed."
        )

    if not collected:
        LOG.info(
            "No new unique announcements. CSV unchanged."
        )
        return 0

    combined = pd.concat(
        [existing, pd.DataFrame(collected)],
        ignore_index=True,
    )

    combined = combined.reindex(
        columns=list(
            dict.fromkeys([
                *existing.columns,
                *COLUMNS,
            ])
        ),
        fill_value="",
    )

    if dry_run:
        LOG.info(
            "DRY RUN: would add %s records.",
            len(collected),
        )
        LOG.info("CSV was NOT changed.")

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
            "Added %s records. Total: %s",
            len(collected),
            len(combined),
        )

    for sponsor in sorted({
        row["source_pe_firm"]
        for row in collected
    }):
        count = sum(
            row["source_pe_firm"] == sponsor
            for row in collected
        )

        LOG.info(
            "%s: %s new announcements",
            sponsor,
            count,
        )

    return len(collected)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Collect Norwest and Tonka Bay "
            "historical announcements"
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
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--source",
        choices=["all", "nep", "tonka"],
        default="all",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        selected = (
            ()
            if args.source == "all"
            else (args.source,)
        )

        update(
            Path(args.csv),
            max_items=max(1, args.max_items),
            delay=max(0.5, args.delay),
            dry_run=args.dry_run,
            enabled_sources=selected,
        )

    except (
        requests.RequestException,
        RuntimeError,
    ) as error:

        LOG.error(
            "Collection failed. CSV preserved: %s",
            error,
        )

        raise SystemExit(1)
