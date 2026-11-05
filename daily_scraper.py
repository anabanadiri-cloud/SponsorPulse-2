"""SponsorPulse daily news collector.

Run: python daily_scraper.py
Dependencies: requests, beautifulsoup4, pandas

New records are automatically classified, NOT independently verified.
Existing CSV rows are preserved. If the source cannot be reached, no data is erased.
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

NEWS_URL = "https://nep.com/news/"
SPONSOR = "Norwest Equity Partners"
HEADERS = {"User-Agent": "SponsorPulseAcademicResearch/1.0 (public news monitoring)"}
COLUMNS = [
    "deal_id", "source_pe_firm", "headline", "url", "announcement_date",
    "collection_date", "is_verified_deal", "transaction_type", "deal_direction",
    "buyer_entity", "target_company", "target_industry", "strategic_rationale",
    "deal_value_disclosed", "evidence_snippet", "review_status",
]
LOG = logging.getLogger("sponsorpulse")


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") + "/", "", "", ""))


def get_html(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def discover_links(soup: BeautifulSoup, max_items: int) -> list[tuple[str, str]]:
    found = {}
    for anchor in soup.select('a[href]'):
        url = canonical_url(urljoin(NEWS_URL, anchor.get('href', '')))
        parsed = urlparse(url)
        if parsed.netloc not in {'nep.com', 'www.nep.com'}:
            continue
        path = parsed.path.strip('/').split('/')
        if len(path) != 2 or path[0] != 'news':
            continue
        headline = anchor.get_text(' ', strip=True)
        if len(headline) < 22 or headline.lower() in {'read more', 'learn more', 'view more'}:
            continue
        found.setdefault(url, headline)
        if len(found) >= max_items:
            break
    return list(found.items())


def article_details(soup: BeautifulSoup, fallback_headline: str) -> tuple[str, str, str]:
    h1 = soup.find('h1')
    headline = h1.get_text(' ', strip=True) if h1 else fallback_headline
    main = soup.find('article') or soup.find('main') or soup
    paragraphs = [p.get_text(' ', strip=True) for p in main.find_all('p')]
    body = ' '.join(p for p in paragraphs if len(p) >= 35)[:12000]
    date = ''
    for key, value in [('property', 'article:published_time'), ('name', 'date'), ('name', 'publish_date')]:
        tag = soup.find('meta', attrs={key: value})
        if tag and tag.get('content'):
            date = tag['content'].strip()
            break
    if not date:
        tag = soup.find('time')
        if tag:
            date = (tag.get('datetime') or tag.get_text(' ', strip=True)).strip()
    if date:
        parsed = pd.to_datetime(date, errors='coerce', utc=True)
        date = parsed.strftime('%Y-%m-%d') if pd.notna(parsed) else ''
    return headline, date, body


def classify(headline: str, body: str) -> dict:
    text = (headline + ' ' + body).lower()
    title = headline.lower()
    if any(x in title for x in ('appoints', 'appointed', 'named partner', 'promoted', 'award', 'volunteer', 'community impact')):
        tx, direction = 'Personnel / Non-Deal', 'OTHER / NON-DEAL'
    elif ('fund' in title or 'capital' in title) and any(x in title for x in ('closes', 'closing', 'raised', 'fundraise')):
        tx, direction = 'Fundraising / Capital Close', 'OTHER / NON-DEAL'
    elif any(x in title for x in ('sale of', 'sells', 'sold to', 'divests', 'exit from')):
        tx, direction = 'Full Exit / Sale', 'SELL / EXIT'
    elif any(x in title for x in ('acquires', 'acquire', 'acquisition of', 'merger with')):
        tx, direction = 'Add-On Acquisition', 'BUY / INVESTMENT'
    elif any(x in title for x in ('investment in', 'invests in', 'investment into')):
        tx, direction = 'Platform Investment', 'BUY / INVESTMENT'
    else:
        tx, direction = 'Needs Manual Review', 'REVIEW REQUIRED'

    buyer, target = '', ''
    if tx == 'Full Exit / Sale':
        match = re.search(r'\bSale of\s+(.+?)\s+to\s+(.+)$', headline, re.I)
        if match:
            target, buyer = match.group(1).strip(), match.group(2).strip()
        else:
            match = re.search(r'\bSells\s+(?:IT Solutions Leader\s+)?(.+?)\s+to\s+(.+)$', headline, re.I)
            if match:
                target, buyer = match.group(1).strip(), match.group(2).strip()
    elif tx == 'Platform Investment':
        match = re.search(r'\bInvestment in\s+(.+?)(?:,|$)', headline, re.I)
        if match:
            target, buyer = match.group(1).strip(), SPONSOR
    elif tx == 'Add-On Acquisition':
        match = re.search(r'(.+?)\s+(?:Announces Agreement to\s+)?Acquires?\s+(.+)', headline, re.I)
        if match:
            buyer, target = match.group(1).strip(), match.group(2).strip()

    if any(x in text for x in ('cybersecurity', 'managed it', 'it solutions', 'software', 'technology')):
        industry = 'Business & IT Services'
    elif any(x in text for x in ('canopy', 'wallcoverings', 'textiles', 'produce', 'food')):
        industry = 'Consumer Products & Distribution'
    elif any(x in text for x in ('manufacturing', 'industrial', 'chemicals', 'bearing')):
        industry = 'Industrial Manufacturing'
    else:
        industry = 'Unknown / Needs Review'

    if any(x in text for x in ('geographic expansion', 'geographic footprint', 'expand its footprint')):
        rationale = 'Geographic Expansion'
    elif any(x in text for x in ('product line', 'product range', 'capability', 'innovation')):
        rationale = 'Product Line & Capability Extension'
    else:
        rationale = 'Not stated / Needs Review'

    disclosed = bool(re.search(r'\$\s*\d+(?:\.\d+)?\s*(?:million|billion|m|bn)\b', text, re.I)) if direction in ('BUY / INVESTMENT', 'SELL / EXIT') else False
    return dict(
        is_verified_deal=False,  # Requires human source validation, even for a likely deal
        transaction_type=tx, deal_direction=direction, buyer_entity=buyer,
        target_company=target, target_industry=industry, strategic_rationale=rationale,
        deal_value_disclosed=disclosed,
        evidence_snippet=(body[:300] if body else headline),
        review_status='Pending manual verification',
    )


def update(csv_path: Path, max_items: int = 30, delay: float = 1.0) -> int:
    existing = pd.read_csv(csv_path, dtype=str, keep_default_na=False) if csv_path.exists() else pd.DataFrame(columns=COLUMNS)
    known = {canonical_url(url) for url in existing.get('url', pd.Series(dtype=str)) if str(url).startswith('http')}
    session = requests.Session()
    session.headers.update(HEADERS)
    soup = get_html(session, NEWS_URL)
    links = discover_links(soup, max_items)
    if not links:
        raise RuntimeError('No article links discovered; existing CSV was left unchanged.')
    LOG.info('Found %s candidate articles', len(links))
    rows = []
    for url, title in links:
        if url in known:
            continue
        time.sleep(delay)
        try:
            article = get_html(session, url)
            headline, date, body = article_details(article, title)
            if not body:
                LOG.warning('Skipping %s: article text missing', url)
                continue
            deal_id = 'NEP_' + hashlib.sha256(url.encode()).hexdigest()[:12]
            rows.append(dict(
                deal_id=deal_id, source_pe_firm=SPONSOR, headline=headline,
                url=url, announcement_date=date,
                collection_date=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                **classify(headline, body),
            ))
            known.add(url)
        except requests.RequestException as exc:
            LOG.warning('Skipping inaccessible article %s: %s', url, exc)
    if not rows:
        LOG.info('No new complete announcements. CSV unchanged.')
        return 0
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    combined = combined.reindex(columns=list(dict.fromkeys([*existing.columns, *COLUMNS])), fill_value='')
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(csv_path, index=False)
    LOG.info('Added %s records; CSV now has %s rows: %s', len(rows), len(combined), csv_path)
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Update SponsorPulse with newly published NEP articles')
    parser.add_argument('--csv', default='deals.csv', help='Existing dashboard CSV path')
    parser.add_argument('--max-items', type=int, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        update(Path(args.csv), max_items=args.max_items)
    except (requests.RequestException, RuntimeError) as exc:
        LOG.error('Collection failed; existing data preserved: %s', exc)
        raise SystemExit(1)
