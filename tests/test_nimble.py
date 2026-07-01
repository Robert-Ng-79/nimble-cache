"""Tests for Nimble asset middleware."""

import tempfile
from pathlib import Path

from nimble.middleware import CacheMiddleware, CacheEntry, AssetKind


class TestCacheMiddleware:
    def test_classify_image(self):
        assert CacheMiddleware._classify_kind(".png") == AssetKind.IMAGE
        assert CacheMiddleware._classify_kind(".jpg") == AssetKind.IMAGE
        assert CacheMiddleware._classify_kind(".svg") == AssetKind.IMAGE

    def test_classify_font(self):
        assert CacheMiddleware._classify_kind(".woff2") == AssetKind.FONT
        assert CacheMiddleware._classify_kind(".ttf") == AssetKind.FONT

    def test_classify_other(self):
        assert CacheMiddleware._classify_kind(".unknown") == AssetKind.OTHER

    def test_extract_py_references(self):
        middleware = CacheMiddleware()
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write('img = open("assets/hero.png", "rb")\n')
            f.write('icon = load("icons/app.svg")\n')
            f.flush()
            refs = middleware._extract_references(Path(f.name))
            assert "assets/hero.png" in refs
            assert "icons/app.svg" in refs
            Path(f.name).unlink()

    def test_md5_computation(self):
        with tempfile.NamedTemporaryFile(suffix=".png", mode="wb", delete=False) as f:
            f.write(b"\x89PNG test content")
            f.flush()
            md5 = CacheMiddleware._md5(Path(f.name))
            assert len(md5) == 32
            Path(f.name).unlink()

    def test_scan_empty_dir(self):
        middleware = CacheMiddleware()
        with tempfile.TemporaryDirectory() as tmp:
            index = middleware.scan(tmp)
            assert index.total_assets == 0
            assert index.orphan_count == 0


class TestCacheEntry:
    def test_size_kb(self):
        record = CacheEntry(
            path="/test/hero.png",
            kind=AssetKind.IMAGE,
            size_bytes=2048,
            extension=".png",
        )
        assert record.size_kb == 2.0

    def test_dimensions(self):
        record = CacheEntry(
            path="/test/hero.png",
            kind=AssetKind.IMAGE,
            size_bytes=1024,
            extension=".png",
            width=1920,
            height=1080,
        )
        assert record.dimensions == "1920x1080"

    def test_default_orphan(self):
        record = CacheEntry(
            path="/test/hero.png",
            kind=AssetKind.IMAGE,
            size_bytes=1024,
            extension=".png",
        )
        assert record.is_orphan
