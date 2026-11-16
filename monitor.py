#!/usr/bin/env python3
"""Weekly sitemap watcher.

Reads the sitemap addresses listed in sitemaps.txt, collects every page URL
(<loc>) in each one, and compares the result with the copy saved last time.
New and removed URLs are written to a dated CSV in docs/deltas/, which the
web page in docs/ lets you browse and download.

Only standard Python is needed.
"""

import csv
import gzip
import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
LIST_FILE = ROOT / "sitemaps.txt"
SNAP_DIR = ROOT / "snapshots"
OUT_DIR = ROOT / "docs" / "deltas"
MANIFEST = OUT_DIR / "manifest.json"

USER_AGENT = "Mozilla/5.0 (compatible; sitemap-watch/1.0)"
MAX_BYTES = 100 * 1024 * 1024  # refuse anything bigger than this
MAX_DEPTH = 3                  # how many levels of sitemap index to follow
PAUSE = 0.5                    # seconds between requests to the same site


def read_list():
    """Sitemap addresses from sitemaps.txt. Blank lines and # comments are ignored."""
    urls = []
    for line in LIST_FILE.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"(^|\s+)#.*$", "", line).strip()
        if line and line not in urls:
            urls.append(line)
    return urls


def site_name(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def slugify(url):
    p = urlparse(url)
    text = site_name(url) + p.path + (("?" + p.query) if p.query else "")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def fetch(url):
    """Download a URL, retrying a few times. Unzips .gz content automatically."""
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,*/*"},
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("file is larger than the size limit")
            if data[:2] == b"\x1f\x8b":  # gzip marker
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                    data = g.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("unzipped file is larger than the size limit")
            return data
        except Exception as error:  # noqa: BLE001 - report whatever went wrong
            last_error = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not download {url} ({last_error})")


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def collect(url, seen, depth=0):
    """Return the set of page URLs in a sitemap, following sitemap indexes."""
    if url in seen:
        return set()
    seen.add(url)
    if depth > MAX_DEPTH:
        raise RuntimeError(f"sitemap index nested too deeply at {url}")

    data = fetch(url)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise RuntimeError(f"{url} is not valid XML ({error})") from error

    # Each <url> or <sitemap> element has one direct <loc> child. Looking only at
    # direct children skips things like image:loc inside image entries.
    locs = []
    for entry in root:
        for el in entry:
            if local_name(el.tag) == "loc" and el.text and el.text.strip():
                locs.append(el.text.strip())

    kind = local_name(root.tag)
    if kind == "urlset":
        return set(locs)
    if kind == "sitemapindex":
        pages = set()
        for child in locs:
            time.sleep(PAUSE)
            pages |= collect(child, seen, depth + 1)
        return pages
    raise RuntimeError(f"{url} has an unexpected top-level element <{kind}>")


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return [tuple(r) for r in list(csv.reader(f))[1:]]


def update_manifest(today, filename, rows, errors):
    """Record this run and, when there were changes, this day's CSV."""
    manifest = {"runs": []}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["last_checked"] = today
    manifest["last_errors"] = errors

    if filename:
        sites = {}
        for _, site, change, _url in rows:
            counts = sites.setdefault(site, {"added": 0, "removed": 0})
            counts[change] += 1
        entry = {
            "date": today,
            "file": filename,
            "added": sum(1 for r in rows if r[2] == "added"),
            "removed": sum(1 for r in rows if r[2] == "removed"),
            "sites": sites,
        }
        manifest["runs"] = [r for r in manifest["runs"] if r["date"] != today] + [entry]
        manifest["runs"].sort(key=lambda r: r["date"], reverse=True)

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    today = datetime.now(timezone.utc).date().isoformat()
    SNAP_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows, errors = [], []
    for sitemap in read_list():
        snapshot = SNAP_DIR / f"{slugify(sitemap)}.txt"
        site = site_name(sitemap)
        try:
            current = collect(sitemap, set())
            if not current:
                raise RuntimeError("no URLs found, so leaving the saved copy alone")
        except Exception as error:  # noqa: BLE001
            message = f"{sitemap}: {error}"
            errors.append(message)
            print(f"::error::{message}")
            continue  # keep last week's copy untouched

        if snapshot.exists():
            previous = set(snapshot.read_text(encoding="utf-8").splitlines()) - {""}
            added = sorted(current - previous)
            removed = sorted(previous - current)
            rows += [(today, site, "added", u) for u in added]
            rows += [(today, site, "removed", u) for u in removed]
            print(f"{sitemap}: {len(current)} URLs, {len(added)} new, {len(removed)} removed")
        else:
            print(f"{sitemap}: first run, saved {len(current)} URLs as the starting point")

        snapshot.write_text("\n".join(sorted(current)) + "\n", encoding="utf-8")

    filename = None
    if rows:
        filename = f"new_urls_{today}.csv"
        path = OUT_DIR / filename
        # If the script is run twice on the same day, keep the earlier findings.
        all_rows = (read_rows(path) if path.exists() else []) + rows
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "site", "change", "url"])
            writer.writerows(all_rows)
        rows = all_rows
    elif (OUT_DIR / f"new_urls_{today}.csv").exists():
        filename = f"new_urls_{today}.csv"
        rows = read_rows(OUT_DIR / filename)

    update_manifest(today, filename, rows, errors)

    # A non-zero exit makes GitHub mark the run as failed and email you.
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
