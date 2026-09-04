#!/usr/bin/env python3
"""Generate a small public search index without modifying existing HTML.

The generated JSON contains only labels, search terms, and public page URLs.
Private catalogue fields, recording URLs, and matching evidence are not emitted.

Person-to-recording matches follow a conservative two-tier rule:

1. An exact dictionary name is present in artist/artist_en/recording metadata.
2. Every track URL in the catalogue record contains the same unambiguous person
   name.  Jacket-only matches are deliberately excluded.

The output path is required so merely running the program cannot overwrite an
existing site artifact by accident.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


SOURCE_ID_RE = re.compile(r"/op\.php\?id=(\d+)(?:&|$)", re.I)
SPACE_RE = re.compile(r"\s+")
OPUS_RE = re.compile(r"\bop\.?\s*(\d+(?:\s*[-–]\s*\d+)?)", re.I)
WORKS_RE = re.compile(r"作品\s*(\d+(?:\s*[の\-–]\s*\d+)?)")
SYMPHONY_RE = re.compile(r"交響曲\s*第?\s*(\d+)\s*番")


def normalized(value: str) -> str:
    """Normalize text for exact dictionary comparisons."""

    value = unicodedata.normalize("NFKC", value).casefold()
    return SPACE_RE.sub(" ", value).strip()


def ascii_key(value: str) -> str:
    """Convert a name or URL to the separator convention used by track paths."""

    value = unicodedata.normalize("NFKD", unquote(value))
    value = value.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(value)).strip()


class PageParser(HTMLParser):
    """Extract only the public fields needed for the search index."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture: str | None = None
        self._buffer: list[str] = []
        self.h1: list[str] = []
        self.breadcrumb_links: list[tuple[str, str]] = []
        self.source_ids: set[str] = set()
        self._anchor_href: str | None = None
        self._anchor_classes: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "h1":
            self._capture = "h1"
            self._buffer = []
        elif tag == "a":
            href = attributes.get("href", "")
            match = SOURCE_ID_RE.search(href)
            if match:
                self.source_ids.add(match.group(1))
            self._anchor_href = href
            self._anchor_classes = set(attributes.get("class", "").split())
            self._capture = "anchor"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._capture == "h1":
            value = clean_text("".join(self._buffer))
            if value:
                self.h1.append(value)
            self._capture = None
            self._buffer = []
        elif tag == "a" and self._capture == "anchor":
            text = clean_text("".join(self._buffer))
            if "breadcrumb" not in self._anchor_classes and self._anchor_href and text:
                self.breadcrumb_links.append((self._anchor_href, text))
            self._anchor_href = None
            self._anchor_classes = set()
            self._capture = None
            self._buffer = []


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def source_id(record: dict[str, object]) -> str | None:
    match = SOURCE_ID_RE.search(str(record.get("source_url", "")))
    return match.group(1) if match else None


def load_people(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    people = data.get("persons") if isinstance(data, dict) else None
    if not isinstance(people, list):
        raise ValueError("persons file must contain a persons array")
    return [person for person in people if isinstance(person, dict)]


def load_composers(path: Path) -> dict[str, dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, dict)
        for key, value in data.items()
    ):
        raise ValueError("composers file must contain an object keyed by composer id")
    return data


def registered_composer_names(composer: dict[str, object]) -> list[str]:
    """Return only explicitly registered composer names and aliases."""

    values: list[object] = [
        composer.get("canonical_name_ja"),
        composer.get("canonical_name_en"),
        *(composer.get("aliases_ja") or []),
        *(composer.get("aliases_en") or []),
    ]
    return unique_terms([value for value in values if isinstance(value, str)])


def person_names(person: dict[str, object]) -> list[str]:
    values: list[object] = [
        person.get("canonical_name"),
        person.get("display_name_ja"),
        person.get("name_en"),
        *(person.get("aliases") or []),
        *(person.get("aliases_en") or []),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        key = normalized(value)
        if key not in seen:
            seen.add(key)
            result.append(clean_text(value))
    return result


def build_person_indexes(
    people: list[dict[str, object]],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, list[str]]]:
    exact: dict[str, set[str]] = defaultdict(set)
    token_owners: dict[str, set[str]] = defaultdict(set)
    public_names: dict[str, list[str]] = {}

    for person in people:
        pid = str(person.get("person_id", "")).strip()
        if not pid:
            continue
        names = person_names(person)
        public_names[pid] = names
        for name in names:
            exact[normalized(name)].add(pid)
        english_values = [person.get("name_en"), *(person.get("aliases_en") or [])]
        for value in english_values:
            if not isinstance(value, str):
                continue
            for token in ascii_key(value).split("_"):
                if len(token) >= 5:
                    token_owners[token].add(pid)

    url_forms: dict[str, set[str]] = defaultdict(set)
    for person in people:
        pid = str(person.get("person_id", "")).strip()
        english_values = [person.get("name_en"), *(person.get("aliases_en") or [])]
        for value in english_values:
            if not isinstance(value, str):
                continue
            form = ascii_key(value)
            if len(form) < 5:
                continue
            if "_" in form or token_owners.get(form) == {pid}:
                url_forms[pid].add(form)

    return exact, url_forms, public_names


def url_has_form(url: str, forms: set[str]) -> bool:
    value = ascii_key(url)
    return any(
        re.search(r"(?:^|_)" + re.escape(form) + r"(?:_|$)", value)
        for form in forms
    )


def metadata_person_ids(
    record: dict[str, object], exact: dict[str, set[str]]
) -> set[str]:
    """Find explicit names without guessing misspellings or identities."""

    text = normalized(
        " | ".join(str(record.get(field, "")) for field in ("artist", "artist_en", "recording"))
    )
    matches: set[str] = set()
    # Prefer substantial labels inside compound metadata. Short labels are used
    # only when the complete cleaned field equals that dictionary label.
    for name, pids in exact.items():
        compact_length = len(name.replace(" ", ""))
        if compact_length >= 6 and name in text:
            matches.update(pids)
    for field in ("artist", "artist_en"):
        value = normalized(str(record.get(field, "")))
        value = re.sub(r"^\([^)]*\)\s*", "", value)
        value = re.sub(r"\s*指揮\s*$", "", value).strip()
        if len(exact.get(value, set())) == 1:
            matches.update(exact[value])
    return matches


def confirmed_people_by_source(
    records: list[dict[str, object]],
    exact: dict[str, set[str]],
    url_forms: dict[str, set[str]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for record in records:
        sid = source_id(record)
        if not sid:
            continue
        result[sid].update(metadata_person_ids(record, exact))
        tracks = record.get("tracks") or []
        urls = [
            str(track.get("url", ""))
            for track in tracks
            if isinstance(track, dict) and str(track.get("url", "")).strip()
        ]
        if not urls:
            continue
        for pid, forms in url_forms.items():
            if forms and all(url_has_form(url, forms) for url in urls):
                result[sid].add(pid)
    return result


def work_variants(title: str) -> list[str]:
    """Add only deterministic, meaning-preserving work-title variants."""

    variants: list[str] = []
    for match in OPUS_RE.finditer(title):
        number = re.sub(r"\s+", "", match.group(1)).replace("–", "-")
        variants.extend((f"作品{number}", f"Op.{number}", f"Op{number}"))
    for match in WORKS_RE.finditer(title):
        number = re.sub(r"\s+", "", match.group(1)).replace("の", "-").replace("–", "-")
        variants.extend((f"作品{number}", f"Op.{number}", f"Op{number}"))
    for match in SYMPHONY_RE.finditer(title):
        number = match.group(1)
        variants.extend((f"交響曲{number}番", f"Symphony No.{number}", f"Symphony No {number}"))
    return variants


def unique_terms(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = clean_text(value)
        key = normalized(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def build_index(
    site_root: Path,
    composers: dict[str, dict[str, object]],
    people: list[dict[str, object]],
    records: list[dict[str, object]],
) -> dict[str, object]:
    exact, url_forms, public_names = build_person_indexes(people)
    people_by_source = confirmed_people_by_source(records, exact, url_forms)
    items: list[dict[str, str]] = []

    composer_display_names: dict[str, str] = {}
    linked_work_pages: set[str] = set()
    composer_dir = site_root / "pages" / "composers"
    for path in sorted(composer_dir.glob("*.html")):
        if path.name == "index.html":
            continue
        page = parse_page(path)
        if not page.h1:
            continue
        name = page.h1[0]
        registered_names = registered_composer_names(composers.get(path.stem, {}))
        if registered_names and normalized(name) not in {
            normalized(value) for value in registered_names
        }:
            raise ValueError(
                f"composer dictionary does not match public page heading: {path}"
            )
        search_names = unique_terms([name, *registered_names])
        composer_display_names[path.stem] = name
        for href, _link_text in page.breadcrumb_links:
            match = re.search(r"(?:^|/)works/([^/]+\.html)$", href)
            if match:
                linked_work_pages.add(match.group(1))
        relative = path.relative_to(site_root).as_posix()
        items.append(
            {"t": "composer", "n": name, "k": " ".join(search_names), "u": relative}
        )

    work_dir = site_root / "pages" / "works"
    for work_name in sorted(linked_work_pages):
        path = work_dir / work_name
        if not path.is_file():
            raise ValueError(f"composer page links to a missing work page: {path}")
        page = parse_page(path)
        if not page.h1:
            continue
        title = page.h1[0]
        composer = ""
        composer_id = ""
        for href, link_text in page.breadcrumb_links:
            match = re.search(r"(?:^|/)composers/([^/]+)\.html$", href)
            if match:
                composer_id = match.group(1)
                composer = composer_display_names.get(composer_id, link_text)
                break
        person_ids: set[str] = set()
        for sid in page.source_ids:
            person_ids.update(people_by_source.get(sid, set()))
        composer_search_names = registered_composer_names(
            composers.get(composer_id, {})
        )
        terms = [title, composer, *composer_search_names, *work_variants(title)]
        for pid in sorted(person_ids):
            terms.extend(public_names.get(pid, []))
        item = {
            "t": "work",
            "n": title,
            "k": " ".join(unique_terms(terms)),
            "u": path.relative_to(site_root).as_posix(),
        }
        if composer:
            item["c"] = composer
        items.append(item)

    items.sort(key=lambda item: (item["t"], normalized(item.get("c", "")), normalized(item["n"]), item["u"]))
    return {"v": 1, "items": items}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, required=True, help="root of the generated public HTML site")
    parser.add_argument("--composers", type=Path, required=True, help="private dictionary/composers.json")
    parser.add_argument("--persons", type=Path, required=True, help="private dictionary/persons.json")
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        nargs="+",
        help="one or more private RAW catalogue JSON files",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON file to create")
    parser.add_argument(
        "--format",
        choices=("json", "js"),
        help="output format (default: inferred from .js suffix, otherwise json)",
    )
    parser.add_argument("--force", action="store_true", help="allow replacement of an existing output file")
    args = parser.parse_args()

    inputs = [
        (args.site_root, "site root"),
        (args.composers, "composers file"),
        (args.persons, "persons file"),
        *((path, "catalogue") for path in args.catalog),
    ]
    for path, label in inputs:
        if not path.exists():
            parser.error(f"{label} not found: {path}")
    if args.output.exists() and not args.force:
        parser.error(f"output already exists (use --force to replace it): {args.output}")

    people = load_people(args.persons)
    composers = load_composers(args.composers)
    catalogue: list[dict[str, object]] = []
    for catalog_path in args.catalog:
        records = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
            parser.error(f"catalogue must be an array of objects: {catalog_path}")
        catalogue.extend(records)

    index = build_index(args.site_root, composers, people, catalogue)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_format = args.format or ("js" if args.output.suffix.casefold() == ".js" else "json")
    payload = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    if output_format == "js":
        payload = "window.BLUE_SKY_SEARCH_INDEX=" + payload + ";"
    args.output.write_text(payload + "\n", encoding="utf-8")
    composer_count = sum(item["t"] == "composer" for item in index["items"])
    work_count = sum(item["t"] == "work" for item in index["items"])
    print(f"wrote {args.output} ({composer_count} composers, {work_count} works)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
