# PyMuPDF extraction notes

The parser uses the official [Page API](https://pymupdf.readthedocs.io/en/latest/page.html) and [Document API](https://pymupdf.readthedocs.io/en/latest/document.html): `get_text("text", sort=True)`, `get_images(full=True)`, `extract_image(xref)`, and `find_tables(strategy="lines")`. See the [text extraction recipes](https://pymupdf.readthedocs.io/en/latest/recipes-text.html) for reading-order limitations. The dependency is pinned to PyMuPDF 1.26.7 and resolved by `pymupdf_parse.py.lock`.

## Output contract

`--format md|json|both` defaults to `md`. `--images` and `--tables` work independently of the text format. `--outroot` defaults to `./pymupdf-output`, relative to the caller's working directory. The final directory uses the input filename without its last extension. Files with the same basename collide even if they come from different folders; use separate output roots. Existing output is never refreshed or merged automatically.

`output.json` has `source` (filename only), `lang` (hint or null), `metadata` (PyMuPDF document metadata), `page_count`, and `pages`. Each page has `number` (one-based), `bbox` (`[x0,y0,x1,y1]` in PDF points), and `text`. With `--images`, each page also has `images`, listing relative paths, object `xref`, pixel dimensions, and the separate `smask` object number if present. Repeated references to the same image on one page are deduplicated; images reused across pages are exported per page.

`tables.json` is a list of objects with `page`, `bbox`, and `rows` (lists of strings or null cells). An empty list means no line-based tables were detected. Table text also remains in the page text. Markdown contains extracted plain text with `## Page N` boundaries; it does not infer headings, equations, references, reading order, or Markdown tables.

The parser imports `pymupdf`, not the unrelated package named `fitz`. It rejects non-PDF files and password-required encrypted PDFs with a nonzero exit and stderr message. For encrypted documents, obtain an authorized decrypted copy; this CLI takes no password and attempts no bypass.

## Environment troubleshooting

Run `uv run --script scripts/pymupdf_parse.py input.pdf` when direct execution is unavailable, or `uv run --locked --script scripts/pymupdf_parse.py input.pdf` to enforce the shipped lockfile. Running `python scripts/pymupdf_parse.py` does not provision dependencies; a missing import directs the caller to uv. If uv is unavailable, report that prerequisite instead of modifying global packages.

On Nix, binary wheels can fail to load native shared libraries. Use the project's existing Nix/development environment if available, or report the native-library failure for the user to resolve in that environment. Do not automatically patch ELF binaries, modify the Nix store, run a remote installer, or install system packages. No particular Nix solution is assumed by this skill.

## Limits and recovery

PyMuPDF is a native parser. Run untrusted or unusually large PDFs within the project's resource limits; there is no memory/time cap in this standalone CLI. It is a separate process, so never move parsing into concurrent threads or an API event loop. When integrating into an async app, keep document parsing in worker child processes with separate request/task state.

Text extraction has no OCR and may be empty on scans. Layout and math can be imperfect. Images are embedded raster objects, not screenshots or vector diagrams; masks are recorded but not composited. Tables are rough line-based candidates, not validated semantic data. Review against the original pages before summarizing or citing a claim.

Output is staged beside the destination, then renamed after extraction. A per-basename lock prevents concurrent copies of this parser from publishing the same target. Ordinary failures remove staging and lock directories. Abrupt termination can leave hidden staging or `.basename.lock`; verify that no parser is running before manually removing those exact artifacts. The output root must be trusted; this is not a defense against another process deliberately mutating filesystem paths during extraction.

Run bundled synthetic behavior tests from this directory:

```sh
uv run --with pymupdf==1.26.7 python -m unittest discover -s tests -v
```

Tests generate disposable PDFs; no uploaded or assignment PDFs are bundled.
