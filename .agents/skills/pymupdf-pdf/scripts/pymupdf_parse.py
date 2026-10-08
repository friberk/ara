#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = ["pymupdf==1.26.7"]
# ///
"""Extract local PDF text, embedded images and line-based tables."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


class ExtractionError(Exception):
    """An actionable input or output failure."""


def json_write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def extract(args: argparse.Namespace) -> Path:
    try:
        import pymupdf
    except ImportError as exc:
        raise ExtractionError(
            "PyMuPDF is unavailable. Run with 'uv run --script <script> <input.pdf>'; "
            "do not install the unrelated 'fitz' package."
        ) from exc

    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise ExtractionError(f"Input PDF is not a regular file: {source}")
    basename = args.input.stem
    if basename in {"", ".", ".."}:
        raise ExtractionError("Input PDF needs a nonempty basename.")
    try:
        doc = pymupdf.open(source)
    except Exception as exc:
        raise ExtractionError(f"Cannot read PDF '{source.name}': {exc}") from exc
    with doc:
        if not doc.is_pdf:
            raise ExtractionError(
                f"Cannot read PDF '{source.name}': input is not a PDF."
            )
        if doc.needs_pass or doc.is_encrypted:
            raise ExtractionError(
                "PDF is encrypted and requires a password; provide an authorized decrypted copy."
            )
        outroot = args.outroot.expanduser().resolve()
        outroot.mkdir(parents=True, exist_ok=True)
        target = outroot / basename
        lock = outroot / f".{basename}.lock"
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise ExtractionError(
                f"Extraction lock already exists: {lock}; check for another running parser."
            ) from exc
        try:
            if os.path.lexists(target):
                raise ExtractionError(
                    f"Output already exists: {target}; choose a different --outroot."
                )
            # Stage in the same filesystem, then publish the complete directory.
            with tempfile.TemporaryDirectory(
                prefix=f".{basename}-", dir=outroot
            ) as staging:
                stage = Path(staging)
                pages = []
                tables = []
                if args.images:
                    (stage / "images").mkdir()
                for number, page in enumerate(doc, start=1):
                    text = page.get_text("text", sort=True)
                    record = {"number": number, "bbox": list(page.rect), "text": text}
                    if args.images:
                        images = []
                        seen = set()
                        for info in page.get_images(full=True):
                            xref = info[0]
                            if xref in seen:
                                continue
                            seen.add(xref)
                            image = doc.extract_image(xref)
                            if not image:
                                continue
                            extension = image["ext"]
                            if not re.fullmatch(r"[a-zA-Z0-9]+", extension):
                                raise ExtractionError(
                                    "Embedded image has an unsafe file extension."
                                )
                            relative = (
                                f"images/page-{number:04d}-xref-{xref}.{extension}"
                            )
                            (stage / relative).write_bytes(image["image"])
                            images.append(
                                {
                                    "path": relative,
                                    "xref": xref,
                                    "width": image["width"],
                                    "height": image["height"],
                                    "smask": info[1],
                                }
                            )
                        record["images"] = images
                    if args.tables:
                        # Consume tables while their owning page is alive.
                        for table in page.find_tables(strategy="lines").tables:
                            tables.append(
                                {
                                    "page": number,
                                    "bbox": list(table.bbox),
                                    "rows": table.extract(),
                                }
                            )
                    pages.append(record)
                data = {
                    "source": source.name,
                    "lang": args.lang,
                    "metadata": doc.metadata or {},
                    "page_count": doc.page_count,
                    "pages": pages,
                }
                if args.format in {"json", "both"}:
                    json_write(stage / "output.json", data)
                if args.format in {"md", "both"}:
                    sections = ["# PDF extraction\n"]
                    for page in pages:
                        sections.append(
                            f"## Page {page['number']}\n\n{page['text'].rstrip()}\n"
                        )
                    (stage / "output.md").write_text(
                        "\n".join(sections), encoding="utf-8"
                    )
                if args.tables:
                    json_write(stage / "tables.json", tables)
                if os.path.lexists(target):
                    raise ExtractionError(
                        f"Output already exists: {target}; choose a different --outroot."
                    )
                stage.rename(target)
        finally:
            lock.rmdir()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local PDF path")
    parser.add_argument("--format", choices=("md", "json", "both"), default="md")
    parser.add_argument(
        "--images", action="store_true", help="Extract embedded raster images"
    )
    parser.add_argument(
        "--tables", action="store_true", help="Extract rough line-based tables"
    )
    parser.add_argument("--outroot", type=Path, default=Path("./pymupdf-output"))
    parser.add_argument(
        "--lang", help="Language hint recorded in JSON; does not enable OCR"
    )
    args = parser.parse_args()
    try:
        output = extract(args)
    except (ExtractionError, OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
