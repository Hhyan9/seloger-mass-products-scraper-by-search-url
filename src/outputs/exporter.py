import csv
import json
import logging
import os
from html import escape
from typing import Any, Dict, Iterable, List

LOGGER = logging.getLogger("seloger_scraper.exporter")

def export_listings(
    listings: Iterable[Dict[str, Any]],
    path: str,
    fmt: str = "json",
) -> None:
    """
    Export listings to JSON, CSV or HTML.

    :param listings: Iterable of listing dicts.
    :param path: Output path.
    :param fmt: 'json', 'csv' or 'html'.
    """
    fmt = fmt.lower()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    listings_list: List[Dict[str, Any]] = list(listings)

    if fmt == "json":
        _export_json(listings_list, path)
    elif fmt == "csv":
        _export_csv(listings_list, path)
    elif fmt == "html":
        _export_html(listings_list, path)
    else:
        raise ValueError(f"Unsupported export format: {fmt}")

    LOGGER.info("Exported %d listings as %s to %s", len(listings_list), fmt.upper(), path)

def _export_json(listings: List[Dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)

def _export_csv(listings: List[Dict[str, Any]], path: str) -> None:
    if not listings:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        return

    # Flatten lists for CSV
    def flatten_value(value: Any) -> str:
        if isinstance(value, list):
            return "; ".join(str(v) for v in value)
        return "" if value is None else str(value)

    fieldnames = sorted({key for item in listings for key in item.keys()})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in listings:
            row = {k: flatten_value(item.get(k)) for k in fieldnames}
            writer.writerow(row)

def _export_html(listings: List[Dict[str, Any]], path: str) -> None:
    if not listings:
        html = "<html><body><p>No listings found.</p></body></html>"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return

    fieldnames = sorted({key for item in listings for key in item.keys()})
    rows_html = []

    for item in listings:
        cells = []
        for key in fieldnames:
            value = item.get(key)
            if isinstance(value, list):
                display = "<br>".join(escape(str(v)) for v in value)
            else:
                display = escape("" if value is None else str(value))
            cells.append(f"<td>{display}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    header_cells = "".join(f"<th>{escape(str(k))}</th>" for k in fieldnames)
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        "<tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>SeLoger Listings Export</title>
    <style>
      body {{ font-family: Arial, sans-serif; font-size: 14px; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ padding: 4px 8px; }}
      th {{ background-color: #f0f0f0; text-align: left; }}
      tbody tr:nth-child(even) {{ background-color: #fafafa; }}
    </style>
  </head>
  <body>
    <h1>SeLoger Listings Export</h1>
    {table_html}
  </body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)