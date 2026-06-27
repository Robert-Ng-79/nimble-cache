"""
Static asset scanner — discovers images, fonts, CSS, and media files.

Walks repository trees, extracts metadata (dimensions, file size, format),
computes perceptual hashes for duplicate image detection, and tracks
asset usage via import/reference analysis in source files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

logger = logging.getLogger("gleam.scanner")


class AssetKind(Enum):
    IMAGE = auto()
    FONT = auto()
    CSS = auto()
    MEDIA = auto()
    DOCUMENT = auto()
    DATA = auto()
    OTHER = auto()


@dataclass
class AssetRecord:
    """Metadata record for a discovered static asset."""

    path: str
    kind: AssetKind
    size_bytes: int
    extension: str
    mime_type: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None  # for media
    phash: str = ""  # perceptual hash for images
    md5: str = ""
    referenced_by: List[str] = field(default_factory=list)
    is_orphan: bool = True
    last_modified: float = 0.0
    line_count: Optional[int] = None  # for CSS/text assets

    @property
    def size_kb(self) -> float:
        return self.size_bytes / 1024

    @property
    def dimensions(self) -> Optional[str]:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None


@dataclass
class AssetIndex:
    """Complete index of all assets found in a repository."""

    repo_path: str
    scanned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_assets: int = 0
    total_bytes: int = 0
    by_kind: Dict[str, int] = field(default_factory=dict)
    by_extension: Dict[str, int] = field(default_factory=dict)
    orphans: List[AssetRecord] = field(default_factory=list)
    duplicates: List[Tuple[AssetRecord, AssetRecord]] = field(default_factory=list)
    assets: List[AssetRecord] = field(default_factory=list)

    @property
    def orphan_count(self) -> int:
        return len(self.orphans)

    @property
    def orphan_bytes(self) -> int:
        return sum(a.size_bytes for a in self.orphans)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo_path,
            "scanned_at": self.scanned_at.isoformat(),
            "total_assets": self.total_assets,
            "total_bytes": self.total_bytes,
            "by_kind": self.by_kind,
            "by_extension": self.by_extension,
            "orphan_count": self.orphan_count,
            "orphan_bytes": self.orphan_bytes,
            "duplicate_groups": len(self.duplicates),
        }


class AssetScanner:
    """Scans a repository for static assets and analyzes usage.

    Detects orphaned (unreferenced) assets, duplicate images via
    perceptual hashing, and oversized files that bloat repositories.
    """

    EXCLUDE_DIRS = {".git", ".hg", "node_modules", "__pycache__", ".venv",
                    "vendor", "target", "build", "dist", "coverage"}
    EXCLUDE_FILES = {".gitkeep", ".gitignore", ".DS_Store", "Thumbs.db"}

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                  ".ico", ".bmp", ".tiff", ".avif"}
    FONT_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
    CSS_EXTS = {".css", ".scss", ".sass", ".less"}
    MEDIA_EXTS = {".mp4", ".webm", ".ogv", ".mp3", ".wav", ".ogg", ".flac"}
    DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".zip", ".tar", ".gz", ".rar", ".7z"}
    DATA_EXTS = {".json", ".xml", ".csv", ".tsv", ".yaml", ".yml"}

    # Reference patterns by source file type
    REF_PATTERNS: Dict[str, List[re.Pattern]] = {
        ".py": [
            re.compile(r'(?:open|read|load|import|path)\s*\(\s*["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|ico|webp|css|woff2?|ttf|otf|mp4|json))["\']'),
        ],
        ".js": [
            re.compile(r'(?:import|require)\s*\(\s*["\']\.?/?([^"\']+\.(?:png|jpg|jpeg|gif|svg|css|woff2?|ttf|json))["\']\)'),
            re.compile(r'["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|webp|ico))["\']'),
        ],
        ".ts": [
            re.compile(r'(?:import|require)\s*\(\s*["\']\.?/?([^"\']+\.(?:png|jpg|jpeg|gif|svg|css|woff2?|ttf|json))["\']\)'),
        ],
        ".tsx": [
            re.compile(r'(?:import|require)\s*\(\s*["\']\.?/?([^"\']+\.(?:png|jpg|jpeg|gif|svg|css|woff2?|ttf|json))["\']\)'),
            re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|webp|ico))["\']'),
        ],
        ".html": [
            re.compile(r'(?:src|href|srcset)\s*=\s*["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|webp|ico|css|woff2?|ttf|js|json))["\']'),
        ],
        ".css": [
            re.compile(r'url\(\s*["\']?([^"\')\s]+\.(?:png|jpg|jpeg|gif|svg|webp|woff2?|ttf|otf))["\']?\s*\)'),
        ],
        ".md": [
            re.compile(r'!\[.*?\]\(([^)]+\.(?:png|jpg|jpeg|gif|svg|webp))\)'),
        ],
    }

    SOURCE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm",
                   ".css", ".scss", ".sass", ".less", ".md", ".mdx",
                   ".java", ".go", ".rs", ".rb", ".php", ".c", ".cpp", ".h"}

    def __init__(self, max_file_mb: int = 50):
        self.max_file_bytes = max_file_mb * 1024 * 1024

    def scan(self, root: str | Path) -> AssetIndex:
        """Full scan of a repository directory."""
        root_path = Path(root).resolve()
        logger.info("Scanning: %s", root_path)
        all_references: Dict[str, List[str]] = defaultdict(list)
        for source_file in self._walk_sources(root_path):
            refs = self._extract_references(source_file)
            for ref in refs:
                resolved = self._resolve_ref(source_file, ref)
                if resolved:
                    all_references[resolved].append(str(source_file.relative_to(root_path)))

        index = AssetIndex(repo_path=str(root_path))
        phash_groups: Dict[str, List[AssetRecord]] = defaultdict(list)

        for asset_file in self._walk_assets(root_path):
            record = self._analyze_asset(asset_file, root_path)
            rel_path = str(asset_file.relative_to(root_path))
            if rel_path in all_references:
                record.referenced_by = all_references[rel_path]
                record.is_orphan = False
            index.assets.append(record)
            index.total_assets += 1
            index.total_bytes += record.size_bytes
            kind_key = record.kind.name.lower()
            index.by_kind[kind_key] = index.by_kind.get(kind_key, 0) + 1
            ext_key = record.extension
            index.by_extension[ext_key] = index.by_extension.get(ext_key, 0) + 1
            if record.is_orphan:
                index.orphans.append(record)
            if record.phash:
                phash_groups[record.phash].append(record)

        for records in phash_groups.values():
            if len(records) > 1:
                for i in range(len(records)):
                    for j in range(i + 1, len(records)):
                        index.duplicates.append((records[i], records[j]))

        index.orphans.sort(key=lambda a: -a.size_bytes)
        return index

    def _walk_sources(self, root: Path) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.EXCLUDE_DIRS]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.suffix.lower() in self.SOURCE_EXTS:
                    if fpath.stat().st_size < self.max_file_bytes:
                        yield fpath

    def _walk_assets(self, root: Path) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.EXCLUDE_DIRS]
            for fname in filenames:
                if fname in self.EXCLUDE_FILES:
                    continue
                fpath = Path(dirpath) / fname
                ext = fpath.suffix.lower()
                all_exts = (self.IMAGE_EXTS | self.FONT_EXTS | self.CSS_EXTS |
                            self.MEDIA_EXTS | self.DOC_EXTS | self.DATA_EXTS)
                if ext in all_exts:
                    if fpath.stat().st_size < self.max_file_bytes:
                        yield fpath

    def _extract_references(self, filepath: Path) -> List[str]:
        refs: List[str] = []
        ext = filepath.suffix.lower()
        patterns = self.REF_PATTERNS.get(ext, [])
        if not patterns:
            return refs
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return refs
        for pat in patterns:
            for m in pat.finditer(text):
                refs.append(m.group(1))
        return refs

    def _resolve_ref(self, source: Path, ref: str) -> Optional[str]:
        """Resolve a relative reference to a canonical repo-relative path."""
        base_dir = source.parent
        try:
            resolved = (base_dir / ref).resolve()
        except Exception:
            return None
        return str(resolved)

    def _analyze_asset(self, filepath: Path, root: Path) -> AssetRecord:
        stat = filepath.stat()
        ext = filepath.suffix.lower()
        kind = self._classify_kind(ext)
        record = AssetRecord(
            path=str(filepath.relative_to(root)),
            kind=kind,
            size_bytes=stat.st_size,
            extension=ext,
            mime_type=mimetypes.guess_type(str(filepath))[0] or "",
            md5=self._md5(filepath),
            last_modified=stat.st_mtime,
        )
        if kind == AssetKind.IMAGE:
            record.phash = self._phash(filepath)
            dims = self._image_dims(filepath)
            if dims:
                record.width, record.height = dims
        elif kind == AssetKind.CSS:
            record.line_count = filepath.read_text(encoding="utf-8", errors="replace").count("\n")
        return record

    @staticmethod
    def _classify_kind(ext: str) -> AssetKind:
        if ext in AssetScanner.IMAGE_EXTS:
            return AssetKind.IMAGE
        if ext in AssetScanner.FONT_EXTS:
            return AssetKind.FONT
        if ext in AssetScanner.CSS_EXTS:
            return AssetKind.CSS
        if ext in AssetScanner.MEDIA_EXTS:
            return AssetKind.MEDIA
        if ext in AssetScanner.DOC_EXTS:
            return AssetKind.DOCUMENT
        if ext in AssetScanner.DATA_EXTS:
            return AssetKind.DATA
        return AssetKind.OTHER

    @staticmethod
    def _md5(filepath: Path) -> str:
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _phash(filepath: Path) -> str:
        """Simple perceptual hash for images (downsampled pixel average)."""
        try:
            from PIL import Image
            img = Image.open(filepath).convert("L").resize((16, 16), Image.LANCZOS)
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            bits = "".join("1" if p > avg else "0" for p in pixels)
            return hex(int(bits, 2))[2:]
        except Exception:
            return ""

    @staticmethod
    def _image_dims(filepath: Path) -> Optional[Tuple[int, int]]:
        try:
            from PIL import Image
            with Image.open(filepath) as img:
                return img.size
        except Exception:
            return None
