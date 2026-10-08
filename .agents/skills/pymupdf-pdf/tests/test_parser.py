"""Behavior checks using only disposable, synthetic PDFs.

Run: uv run --with pymupdf==1.26.7 python -m unittest discover -s tests -v
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import pymupdf

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pymupdf_parse.py"


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf = self.root / "sample.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 50), "Synthetic first page")
            pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
            pix.clear_with(128)
            page.insert_image(pymupdf.Rect(50, 80, 90, 120), pixmap=pix)
            for x in (50, 150, 250):
                page.draw_line((x, 160), (x, 240))
            for y in (160, 200, 240):
                page.draw_line((50, y), (250, y))
            for x, y, text in (
                (60, 185, "Name"),
                (160, 185, "Value"),
                (60, 225, "Alpha"),
                (160, 225, "42"),
            ):
                page.insert_text((x, y), text)
            doc.new_page().insert_text((50, 50), "Synthetic second page")
            doc.set_metadata({"title": "Synthetic test"})
            doc.save(self.pdf)

    def tearDown(self):
        self.temp.cleanup()

    def run_parser(self, *args, input_pdf=None):
        return subprocess.run(
            [
                str(SCRIPT),
                str(input_pdf or self.pdf),
                "--outroot",
                str(self.root / "output"),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_default_markdown_has_page_boundaries(self):
        result = self.run_parser()
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.root / "output" / "sample"
        text = (folder / "output.md").read_text()
        self.assertIn("## Page 1", text)
        self.assertIn("## Page 2", text)
        self.assertIn("Synthetic first page", text)
        self.assertFalse((folder / "output.json").exists())

    def test_both_images_tables_and_language(self):
        result = self.run_parser(
            "--format", "both", "--images", "--tables", "--lang", "en"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.root / "output" / "sample"
        data = json.loads((folder / "output.json").read_text())
        self.assertEqual(data["lang"], "en")
        self.assertEqual(data["metadata"]["title"], "Synthetic test")
        self.assertEqual([page["number"] for page in data["pages"]], [1, 2])
        self.assertEqual(len(data["pages"][0]["bbox"]), 4)
        images = list((folder / "images").iterdir())
        self.assertEqual(len(images), 1)
        with pymupdf.open(images[0]) as image_doc:
            self.assertEqual(image_doc.page_count, 1)
        tables = json.loads((folder / "tables.json").read_text())
        self.assertEqual(tables[0]["page"], 1)
        self.assertEqual(tables[0]["rows"], [["Name", "Value"], ["Alpha", "42"]])

    def test_json_only(self):
        result = self.run_parser("--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.root / "output" / "sample"
        self.assertTrue((folder / "output.json").exists())
        self.assertFalse((folder / "output.md").exists())

    def test_existing_output_is_untouched(self):
        result = self.run_parser()
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / "output" / "sample" / "output.md"
        original = path.read_bytes()
        result = self.run_parser("--format", "both")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((path.parent / "output.json").exists())

    def test_malformed_and_encrypted_fail_without_partial_output(self):
        malformed = self.root / "malformed.pdf"
        malformed.write_bytes(b"This is not a PDF")
        encrypted = self.root / "encrypted.pdf"
        with pymupdf.open(self.pdf) as doc:
            doc.save(
                encrypted,
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="owner",
                user_pw="secret",
            )
        for path, message in ((malformed, "Cannot read PDF"), (encrypted, "encrypted")):
            with self.subTest(path=path):
                result = self.run_parser(input_pdf=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse((self.root / "output" / path.stem).exists())

    def test_symlink_destination_is_not_written(self):
        outroot = self.root / "output"
        outroot.mkdir()
        victim = self.root / "victim"
        victim.mkdir()
        (outroot / "sample").symlink_to(victim, target_is_directory=True)
        result = self.run_parser()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(victim.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
