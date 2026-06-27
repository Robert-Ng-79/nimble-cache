"""Gleam — Static asset analyzer and cleanup reporter."""

__version__ = "0.3.0"
__author__ = "Gleam Duster Maintainers"
__all__ = ["AssetScanner", "AssetIndex", "AssetRecord", "CleanupReporter"]

from .scanner import AssetScanner, AssetRecord, AssetIndex
from .reporter import CleanupReporter
