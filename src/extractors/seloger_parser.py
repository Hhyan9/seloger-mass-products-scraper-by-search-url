import concurrent.futures
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .html_cleaner import clean_text, extract_int, extract_float

LOGGER = logging.getLogger("seloger_scraper.seloger_parser")

@dataclass
class ListingSummary:
    title: str
    url: str
    location: Optional[str] = None
    price: Optional[int] = None
    photos: List[str] = field(default_factory=list)

class SeLogerScraper:
    """
    Minimal but realistic scraper for SeLoger search result pages.

    It is structured so that selectors are easy to adjust without
    rewriting the logic.
    """

    def __init__(
        self,
        user_agent: Optional[str] = None,
        timeout: int = 20,
        max_workers: int = 5,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent
                or (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                )
            }
        )
        self.timeout = timeout
        self.max_workers = max_workers

    # ------------- Public API -------------

    def scrape(
        self,
        start_url: str,
        deep_scrape: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        High-level entry: fetch search page, parse summaries and optionally
        enrich with deep listing data.
        """
        LOGGER.debug("Fetching search results from %s", start_url)
        html = self._fetch_url(start_url)
        summaries = self._parse_search_results(html)

        if limit is not None:
            summaries = summaries[:limit]

        LOGGER.info("Parsed %d listing summaries", len(summaries))

        if not deep_scrape:
            return [self._summary_to_dict(s) for s in summaries]

        LOGGER.info("Deep scraping %d listings", len(summaries))
        return self._deep_scrape_summaries(summaries)

    # ------------- Networking -------------

    def _fetch_url(self, url: str) -> str:
        LOGGER.debug("GET %s", url)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    # ------------- Parsing search page -------------

    def _parse_search_results(self, html: str) -> List[ListingSummary]:
        soup = BeautifulSoup(html, "lxml")
        listings: List[ListingSummary] = []

        # SeLoger layout evolves; we combine a few common patterns.
        card_selectors = [
            "div.c-pa-list",              # older result list
            "div.ListingCell",            # generic listing cell
            "article[data-test='sl-card-result']",  # newer test attribute
        ]

        cards = []
        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                LOGGER.debug("Found %d cards with selector '%s'", len(cards), selector)
                break

        if not cards:
            LOGGER.warning("No listing cards found; selectors may be outdated.")
            return []

        for card in cards:
            try:
                title_el = card.select_one("h2, h3, h4, a[data-test='sl-card-title']")
                title = clean_text(title_el.get_text()) if title_el else "Property listing"

                link_el = card.find("a", href=True)
                url = link_el["href"] if link_el else ""
                if url and url.startswith("/"):
                    url = "https://www.seloger.com" + url

                loc_el = card.find(attrs={"data-test": re.compile(".*location.*")}) or card.find(
                    "p", class_=re.compile("Location", re.I)
                )
                location = clean_text(loc_el.get_text()) if loc_el else None

                price_el = card.find(string=re.compile(r"\d[\d\s]*€"))
                price = extract_int(price_el) if price_el else None

                photos: List[str] = []
                for img in card.find_all("img"):
                    src = img.get("data-src") or img.get("src")
                    if src and "seloger.com" in src and src not in photos:
                        photos.append(src)

                if not url:
                    LOGGER.debug("Skipping card without URL")
                    continue

                listings.append(
                    ListingSummary(
                        title=title,
                        url=url,
                        location=location,
                        price=price,
                        photos=photos,
                    )
                )
            except Exception as exc:
                LOGGER.debug("Failed to parse card: %s", exc, exc_info=True)

        return listings

    # ------------- Deep scraping -------------

    def _deep_scrape_summaries(
        self, summaries: List[ListingSummary]
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        def worker(summary: ListingSummary) -> Optional[Dict[str, Any]]:
            try:
                html = self._fetch_url(summary.url)
                detail = self._parse_listing_page(html, summary)
                return detail
            except Exception as exc:
                LOGGER.warning("Failed to deep-scrape %s: %s", summary.url, exc)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(worker, s) for s in summaries]
            for f in concurrent.futures.as_completed(futures):
                result = f.result()
                if result:
                    results.append(result)

        return results

    # ------------- Parsing listing page -------------

    def _parse_listing_page(
        self, html: str, summary: ListingSummary
    ) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")

        title = summary.title
        title_el = soup.find("h1")
        if title_el:
            title = clean_text(title_el.get_text()) or title

        description = ""
        desc_el = soup.find(attrs={"data-test": "sl-price-description"})
        if not desc_el:
            for selector in [
                "div.Description", 
                "section[data-test='sl-description']",
                "div.c-pa-list-details__text",
            ]:
                desc_el = soup.select_one(selector)
                if desc_el:
                    break
        if desc_el:
            description = clean_text(desc_el.get_text())

        # Price
        price = summary.price
        price_el = soup.find(string=re.compile(r"\d[\d\s]*€"))
        if price_el:
            price = extract_int(price_el)

        # Location
        location = summary.location
        loc_el = soup.find(attrs={"data-test": re.compile(".*location.*")})
        if not loc_el:
            loc_el = soup.find("p", class_=re.compile("Localisation|Adresse", re.I))
        if loc_el:
            location = clean_text(loc_el.get_text())

        # Energy info
        energy_info = None
        energy_block = soup.find(string=re.compile(r"Classe\s+[A-G]", re.I))
        if energy_block:
            energy_info = clean_text(energy_block)
        else:
            label_el = soup.find(
                string=re.compile(r"diagnostic de performance énergétique", re.I)
            )
            if label_el and label_el.parent:
                energy_info = clean_text(label_el.parent.get_text())

        # Construction date / year
        construction_date = None
        year_match = re.search(r"(Construction\s+en\s+)?(19|20)\d{2}", html)
        if year_match:
            construction_date = year_match.group(0).split()[-1]

        # Publisher info
        publisher_name = None
        publisher_email = None
        publisher_phone = None

        # Name is often in agency card
        agency_selectors = [
            "div[data-test='sl-contact-info']",
            "div.AgencyCard",
            "div[data-test='agency-card']",
        ]
        for selector in agency_selectors:
            agency = soup.select_one(selector)
            if agency:
                if not publisher_name:
                    name_el = agency.find(["h2", "h3"])
                    if name_el:
                        publisher_name = clean_text(name_el.get_text())
                if not publisher_phone:
                    phone_el = agency.find(string=re.compile(r"\+?\d[\d\s]{6,}"))
                    if phone_el:
                        publisher_phone = clean_text(phone_el)
                if not publisher_email:
                    email_el = agency.find("a", href=re.compile(r"mailto:", re.I))
                    if email_el:
                        publisher_email = email_el["href"].split(":", 1)[-1]
                break

        if not publisher_phone:
            phone_el = soup.find("a", href=re.compile(r"tel:", re.I))
            if phone_el:
                publisher_phone = phone_el["href"].split(":", 1)[-1]

        if not publisher_email:
            email_el = soup.find("a", href=re.compile(r"mailto:", re.I))
            if email_el:
                publisher_email = email_el["href"].split(":", 1)[-1]

        # Nearby transport
        nearby_transport: List[str] = []
        transport_block = soup.find(string=re.compile(r"Transport|Métro|Bus", re.I))
        if transport_block and transport_block.parent:
            text = transport_block.parent.get_text(" ", strip=True)
            pieces = re.split(r"[•\n]", text)
            for p in pieces:
                p = clean_text(p)
                if p and ("métro" in p.lower() or "bus" in p.lower()):
                    nearby_transport.append(p)

        # Photos
        photos = summary.photos[:]
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src and "seloger.com" in src and src not in photos:
                photos.append(src)

        data: Dict[str, Any] = {
            "title": title,
            "description": description,
            "price": price,
            "location": location,
            "photos": photos,
            "energy_info": energy_info,
            "construction_date": construction_date,
            "publisher_name": publisher_name,
            "publisher_email": publisher_email,
            "publisher_phone": publisher_phone,
            "nearby_transport": nearby_transport,
            "url": summary.url,
            "scraped_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }

        return data

    # ------------- Helpers -------------

    @staticmethod
    def _summary_to_dict(summary: ListingSummary) -> Dict[str, Any]:
        return {
            "title": summary.title,
            "description": "",
            "price": summary.price,
            "location": summary.location,
            "photos": summary.photos,
            "energy_info": None,
            "construction_date": None,
            "publisher_name": None,
            "publisher_email": None,
            "publisher_phone": None,
            "nearby_transport": [],
            "url": summary.url,
            "scraped_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }