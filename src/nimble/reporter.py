"""Cleanup report generator for asset analysis results."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .middleware import CacheIndex, CacheEntry, AssetKind


class CacheReporter:
    """Generates human-readable and JSON cleanup manifests from asset scans."""

    def summarize(self, index: CacheIndex) -> Dict[str, Any]:
        savings = index.orphan_bytes
        dup_bytes = sum(a.size_bytes for a, _ in index.duplicates)
        return {
            "repo": index.repo_path,
            "total_assets": index.total_assets,
            "total_mb": round(index.total_bytes / (1024 * 1024), 2),
            "orphans": {
                "count": index.orphan_count,
                "total_mb": round(savings / (1024 * 1024), 2),
                "top_10": [
                    {
                        "path": a.path,
                        "kind": a.kind.name.lower(),
                        "size_kb": round(a.size_kb, 1),
                        "dimensions": a.dimensions,
                    }
                    for a in index.orphans[:10]
                ],
            },
            "duplicates": {
                "groups": len(index.duplicates),
                "wasted_mb": round(dup_bytes / (1024 * 1024), 2),
            },
        }

    def render_text(self, index: CacheIndex) -> str:
        s = self.summarize(index)
        lines = [
            f"Asset Analysis Report: {s['repo']}",
            "=" * 50,
            f"Total assets: {s['total_assets']} ({s['total_mb']} MB)",
            f"Breakdown: {json.dumps(index.by_kind)}",
            "",
            f"Orphans: {s['orphans']['count']} files ({s['orphans']['total_mb']} MB)",
        ]
        if s["orphans"]["top_10"]:
            lines.append("  Top orphaned by size:")
            for o in s["orphans"]["top_10"]:
                dims = f" [{o['dimensions']}]" if o["dimensions"] else ""
                lines.append(f"    {o['size_kb']:>8.1f} KB  {o['path']}{dims}")
        lines.append(f"\nDuplicates: {s['duplicates']['groups']} groups "
                     f"({s['duplicates']['wasted_mb']} MB wasted)")
        return "\n".join(lines)

    def render_json(self, index: CacheIndex) -> str:
        return json.dumps(self.summarize(index), indent=2, ensure_ascii=False)
