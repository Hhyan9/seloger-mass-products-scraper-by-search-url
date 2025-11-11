import argparse
import json
import logging
import os
from typing import Any, Dict, List, Optional

from extractors.seloger_parser import SeLogerScraper
from outputs.exporter import export_listings
from datetime import datetime

LOGGER = logging.getLogger("seloger_scraper")

def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    LOGGER.debug("Logging initialized with level %s", logging.getLevelName(level))

def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    LOGGER.debug("Loaded configuration from %s", path)
    return cfg

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SeLoger Mass Products Scraper (by search URL)"
    )
    parser.add_argument(
        "--config",
        "-c",
        default=os.path.join(
            os.path.dirname(__file__), "config", "settings.example.json"
        ),
        help="Path to JSON configuration file.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "output.json"),
        help="Path to output file. If omitted, uses config or defaults to data/output.json",
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        action="count",
        default=0,
        help="Increase logging verbosity (use -v or -vv).",
    )
    return parser.parse_args()

def read_inputs_file(path: str) -> List[str]:
    if not os.path.exists(path):
        LOGGER.warning("Inputs file does not exist: %s", path)
        return []

    urls: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and not url.startswith("#"):
                urls.append(url)

    LOGGER.info("Loaded %d start URLs from %s", len(urls), path)
    return urls

def read_previous_listings(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        LOGGER.info("No previous output file found at %s; delta mode will treat all as new.", path)
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            LOGGER.warning("Previous output file did not contain a list; ignoring.")
            return []
        LOGGER.info("Loaded %d previous listings from %s", len(data), path)
        return data
    except Exception as exc:
        LOGGER.error("Failed to read previous output: %s", exc)
        return []

def compute_delta(
    previous: List[Dict[str, Any]], current: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    prev_by_url = {item.get("url"): item for item in previous if item.get("url")}
    curr_by_url = {item.get("url"): item for item in current if item.get("url")}

    prev_urls = set(prev_by_url.keys())
    curr_urls = set(curr_by_url.keys())

    new_urls = curr_urls - prev_urls
    removed_urls = prev_urls - curr_urls

    new_listings = [curr_by_url[u] for u in new_urls]
    removed_listings = [prev_by_url[u] for u in removed_urls]

    LOGGER.info("Delta mode: %d new, %d removed listings", len(new_listings), len(removed_listings))
    return {
        "new": new_listings,
        "removed": removed_listings,
        "current": current,
    }

def main() -> None:
    args = parse_args()
    setup_logging(args.verbosity)

    try:
        config = load_config(args.config)
    except Exception as exc:
        LOGGER.error("Unable to load configuration: %s", exc)
        raise SystemExit(1)

    start_url: Optional[str] = config.get("start_url")
    inputs_file: Optional[str] = config.get("inputs_file")
    deep_scrape: bool = bool(config.get("deep_scrape", False))
    delta_mode: bool = bool(config.get("delta_mode", False))
    output_format: str = str(config.get("output_format", "json")).lower()
    output_path: str = config.get("output_path") or args.output
    previous_output_path: str = config.get("previous_output_path") or output_path
    max_results: Optional[int] = config.get("max_results")

    if not start_url and inputs_file:
        # Load first URL from inputs file
        potential_urls = read_inputs_file(inputs_file)
        start_url = potential_urls[0] if potential_urls else None

    if not start_url:
        LOGGER.error("No start_url provided in config and no valid URL in inputs file.")
        raise SystemExit(1)

    scraper = SeLogerScraper(
        user_agent=config.get("user_agent"),
        timeout=config.get("timeout", 20),
        max_workers=config.get("max_workers", 5),
    )

    LOGGER.info(
        "Starting scrape for %s (deep_scrape=%s, delta_mode=%s)",
        start_url,
        deep_scrape,
        delta_mode,
    )

    try:
        listings = scraper.scrape(start_url=start_url, deep_scrape=deep_scrape, limit=max_results)
    except Exception as exc:
        LOGGER.error("Scraping failed: %s", exc, exc_info=True)
        raise SystemExit(1)

    # Attach scraped_at timestamp if missing
    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for listing in listings:
        if "scraped_at" not in listing:
            listing["scraped_at"] = timestamp

    result_payload: Any = listings

    if delta_mode:
        previous_listings = read_previous_listings(previous_output_path)
        deltas = compute_delta(previous_listings, listings)
        # For export we still write the full current snapshot; deltas are logged
        result_payload = deltas["current"]
        LOGGER.info(
            "Delta summary - total current: %d, new: %d, removed: %d",
            len(deltas["current"]),
            len(deltas["new"]),
            len(deltas["removed"]),
        )

    try:
        export_listings(result_payload, output_path, output_format)
    except Exception as exc:
        LOGGER.error("Failed to export listings: %s", exc, exc_info=True)
        raise SystemExit(1)

    LOGGER.info(
        "Scraping complete. %d listings exported to %s as %s.",
        len(listings),
        output_path,
        output_format.upper(),
    )

if __name__ == "__main__":
    main()