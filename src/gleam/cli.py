"""Gleam CLI — scan repositories for orphaned and duplicate assets."""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .scanner import AssetScanner
from .reporter import CleanupReporter


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stderr)


@click.group()
@click.version_option(version=__version__, prog_name="gleam")
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """Gleam — Static asset analyzer and cleanup reporter."""
    setup_logging(verbose)
    ctx.ensure_object(dict)


@main.command()
@click.argument("repo", type=click.Path(exists=True))
@click.option("-o", "--output", type=click.Path(), help="Output JSON report")
@click.option("-f", "--format", "output_format",
              type=click.Choice(["text", "json"]), default="text")
@click.option("--max-mb", type=int, default=50,
              help="Maximum file size to analyze (MB)")
def scan(repo: str, output: Optional[str], output_format: str, max_mb: int) -> None:
    """Scan a repository for static assets."""
    scanner = AssetScanner(max_file_mb=max_mb)
    index = scanner.scan(repo)
    reporter = CleanupReporter()

    if output_format == "json":
        out = reporter.render_json(index)
    else:
        out = reporter.render_text(index)

    if output:
        Path(output).write_text(out, encoding="utf-8")
        click.echo(f"Report written to {output}")
    else:
        click.echo(out)


if __name__ == "__main__":
    main()
