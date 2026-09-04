#!/usr/bin/env python3
"""Tests for the public-page boundary of build_search_index.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("build_search_index.py")
SPEC = importlib.util.spec_from_file_location("build_search_index", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def page(title: str, body: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>{title}</title></head>
<body><main><h1>{title}</h1>{body}</main></body></html>
"""


class PublicHtmlBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "pages" / "composers").mkdir(parents=True)
        (self.root / "pages" / "works").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> None:
        (self.root / relative).write_text(content, encoding="utf-8")

    def test_only_work_pages_linked_from_current_composer_pages_are_indexed(self) -> None:
        self.write(
            "pages/composers/corelli.html",
            page(
                "コレッリ",
                '<a href="../works/corelli-current.html">クリスマス協奏曲</a>',
            ),
        )
        self.write(
            "pages/works/corelli-current.html",
            page(
                "合奏協奏曲 作品6 第8番 ト短調 (クリスマス協奏曲)",
                '<a href="http://www.yung.jp/yungdb/op.php?id=2164">音源</a>',
            ),
        )
        self.write(
            "pages/works/corelli-obsolete.html",
            page(
                "合奏協奏曲 作品6 第8番 ト短調 (クリスマス協奏曲)",
                '<a href="http://www.yung.jp/yungdb/op.php?id=2153">旧版音源</a>',
            ),
        )

        index = MODULE.build_index(self.root, {}, [], [])
        work_urls = [item["u"] for item in index["items"] if item["t"] == "work"]

        self.assertEqual(work_urls, ["pages/works/corelli-current.html"])
        self.assertNotIn("pages/works/corelli-obsolete.html", work_urls)

    def test_missing_linked_work_page_is_an_error(self) -> None:
        self.write(
            "pages/composers/corelli.html",
            page(
                "コレッリ",
                '<a href="../works/corelli-missing.html">存在しない作品</a>',
            ),
        )

        with self.assertRaisesRegex(ValueError, "missing work page"):
            MODULE.build_index(self.root, {}, [], [])

    def test_registered_composer_aliases_are_searchable(self) -> None:
        self.write(
            "pages/composers/beethoven.html",
            page(
                "ベートーヴェン",
                '<a href="../works/beethoven-symphony-5.html">交響曲第5番</a>',
            ),
        )
        self.write(
            "pages/works/beethoven-symphony-5.html",
            page(
                "交響曲第5番 ハ短調 作品67『運命』",
                '<a href="../composers/beethoven.html">ベートーヴェン</a>',
            ),
        )
        composers = {
            "beethoven": {
                "canonical_name_ja": "ベートーヴェン",
                "canonical_name_en": "Ludwig van Beethoven",
                "aliases_ja": ["ベートーベン"],
                "aliases_en": ["Beethoven"],
            }
        }

        index = MODULE.build_index(self.root, composers, [], [])
        composer = next(item for item in index["items"] if item["t"] == "composer")
        work = next(item for item in index["items"] if item["t"] == "work")

        for term in ("ベートーヴェン", "ベートーベン", "Beethoven"):
            self.assertIn(term, composer["k"])
            self.assertIn(term, work["k"])

    def test_mismatched_composer_dictionary_is_an_error(self) -> None:
        self.write("pages/composers/beethoven.html", page("ベートーヴェン"))
        composers = {
            "beethoven": {
                "canonical_name_ja": "モーツァルト",
                "canonical_name_en": "Wolfgang Amadeus Mozart",
            }
        }

        with self.assertRaisesRegex(ValueError, "does not match public page"):
            MODULE.build_index(self.root, composers, [], [])


if __name__ == "__main__":
    unittest.main()
