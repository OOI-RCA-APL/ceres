#!/usr/bin/env python3

"""Generate a PEP 503 package index from the repository's GitHub release assets.

The index is static HTML the GitHub Pages site serves under `/simple/`, so `pip` and
`uv` resolve released wheels straight from GitHub with no PyPI involved. Each release's
wheel and sdist assets become one anchor per file, with a `#sha256=...` fragment when
the API reports the asset's digest.

Runs on the standard library alone, taking the repository from `GITHUB_REPOSITORY` and
an optional token from `GITHUB_TOKEN` for rate limits.
"""

import argparse
import html
import json
import os
import sys
import urllib.request
from pathlib import Path

# ruff: disable[T201] # Allow print statements.

_PROJECT = "ceres"
"""The one distribution this repository publishes, already in PEP 503 normalized form."""


def _releases(repository: str, token: str | None) -> list[dict]:
    """Fetch every release of the repository, following pagination."""
    releases: list[dict] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        with urllib.request.urlopen(request) as response:
            batch = json.load(response)

        if not batch:
            return releases

        releases.extend(batch)
        page += 1


def _anchor(asset: dict) -> str | None:
    """Return the index anchor for one release asset, or None for a non-package file."""
    name = asset["name"]
    if not name.endswith((".whl", ".tar.gz")):
        return None

    url = asset["browser_download_url"]
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        url = f"{url}#sha256={digest.removeprefix('sha256:')}"

    return f'    <a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'


def _page(title: str, body: list[str]) -> str:
    """Render one index page in the shape PEP 503 requires."""
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "  <head>",
        '    <meta name="pypi:repository-version" content="1.0">',
        f"    <title>{html.escape(title)}</title>",
        "  </head>",
        "  <body>",
        *body,
        "  </body>",
        "</html>",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the package index from releases.")
    parser.add_argument("output", type=Path, help="Directory to write the index under.")
    options = parser.parse_args()

    repository = os.environ.get("GITHUB_REPOSITORY", "OOI-RCA-APL/ceres")
    token = os.environ.get("GITHUB_TOKEN")

    anchors = [
        anchor
        for release in _releases(repository, token)
        for asset in release.get("assets", [])
        if (anchor := _anchor(asset)) is not None
    ]
    if not anchors:
        print("No package assets found on any release.", file=sys.stderr)

    root = options.output
    (root / _PROJECT).mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        _page("Simple index", [f'    <a href="{_PROJECT}/">{_PROJECT}</a>'])
    )
    (root / _PROJECT / "index.html").write_text(_page(f"Links for {_PROJECT}", anchors))
    print(f"Wrote {len(anchors)} file link(s) for {_PROJECT}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
