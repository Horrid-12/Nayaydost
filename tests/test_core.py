"""Fast, dependency-free regression tests for NyayaDost's core.

Run from the project root:

    ./venv/bin/python -m unittest discover -s tests -v

The tests exercise the deterministic rulebook, locale catalogs, PDF parser,
NyayaGuide content, and legal-aid lookup. They do not need a running server or
a Sarvam API key.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from server.errors import DocumentError
from server.services.content import (
    find_legal_aid,
    get_guide,
    get_legal_aid_options,
    get_samples,
)
from server.services.document_parser import parse_pdf_bytes
from server.services.localization import NOTICE_IDS, get_locale_store
from server.services.simplifier import analyze_notice, extract_amount

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PDF = ROOT / "tests" / "fixtures" / "sample_notice.pdf"
LANGUAGES = ("en", "hi", "mr", "gu", "ta", "te", "bn")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


class LocaleCatalogTests(unittest.TestCase):
    def test_every_locale_has_the_same_schema(self) -> None:
        store = get_locale_store()
        self.assertEqual(set(store.locales), set(LANGUAGES))
        for code in LANGUAGES:
            with self.subTest(language=code):
                locale = store.get(code)
                labels = store.labels(code)
                self.assertTrue(locale["labels"])
                self.assertTrue(locale["glossary"])
                self.assertEqual(set(locale["notices"]), set(NOTICE_IDS))
                self.assertGreaterEqual(len(locale["common_steps"]), 5)
                for key in (
                    "summary",
                    "deadlines",
                    "steps",
                    "audio",
                    "original",
                    "glossary",
                    "reply",
                    "disclaimer",
                ):
                    self.assertTrue(labels.get(key), f"missing label {key}")

    def test_sample_notices_cover_every_notice_type(self) -> None:
        samples = get_samples()
        self.assertGreaterEqual(len(samples), 9)
        self.assertEqual({sample.notice_type for sample in samples}, set(NOTICE_IDS))
        for sample in samples:
            with self.subTest(sample=sample.id):
                self.assertGreater(len(sample.text), 200)
                self.assertNotIn("{{", sample.text)


class RulebookTests(unittest.TestCase):
    def test_every_sample_in_every_language(self) -> None:
        for language in LANGUAGES:
            for sample in get_samples():
                with self.subTest(language=language, sample=sample.id):
                    result = analyze_notice(
                        text=sample.text,
                        language=language,
                        source_name=sample.title,
                    )
                    self.assertEqual(result.language, language)
                    self.assertTrue(result.summary_body)
                    self.assertTrue(result.tts_text)
                    self.assertTrue(result.disclaimer)
                    self.assertGreaterEqual(len(result.steps), 5)
                    self.assertTrue(result.deadlines)
                    self.assertTrue(result.facts)
                    self.assertTrue(result.glossary)
                    self.assertTrue(result.reply.template)
                    for text in (
                        result.summary_body,
                        result.tts_text,
                        result.reply.template,
                        result.reply.note,
                        result.reply.subject,
                        result.disclaimer,
                    ):
                        self.assertIsNone(PLACEHOLDER.search(text), text[:160])

    def test_amount_extraction_handles_pdf_line_wraps(self) -> None:
        self.assertEqual(extract_amount("Rs. 1,85,000"), "₹1,85,000")
        self.assertEqual(extract_amount("Rs. 1,85,0\n00 drawn"), "₹1,85,000")
        self.assertEqual(extract_amount("Rs. 1,85,000 15 days"), "₹1,85,000")
        self.assertEqual(extract_amount("INR 2500.50"), "₹2,500.50")
        self.assertIsNone(extract_amount("No amount is stated here."))

    def test_analysis_is_deterministic_for_same_input(self) -> None:
        sample = get_samples()[0]
        first = analyze_notice(sample.text, "en", sample.title)
        second = analyze_notice(sample.text, "en", sample.title)
        self.assertEqual(first.notice_type, second.notice_type)
        self.assertEqual(first.summary_body, second.summary_body)
        self.assertEqual(
            [(item.date, item.days_remaining) for item in first.deadlines],
            [(item.date, item.days_remaining) for item in second.deadlines],
        )
        self.assertNotEqual(first.analysis_id, second.analysis_id)


class PdfParserTests(unittest.TestCase):
    def test_reads_a_text_pdf_without_writing_it_to_disk(self) -> None:
        self.assertTrue(FIXTURE_PDF.exists(), "run the fixture generator first")
        parsed = parse_pdf_bytes(FIXTURE_PDF.read_bytes(), "sample_notice.pdf")
        self.assertEqual(parsed.pages, 1)
        self.assertGreater(parsed.characters, 500)
        self.assertIn("Section 138", parsed.text)
        self.assertEqual(extract_amount(parsed.text), "₹1,85,000")
        self.assertNotIn("{{", parsed.text)

    def test_rejects_an_empty_file(self) -> None:
        with self.assertRaises(DocumentError) as raised:
            parse_pdf_bytes(b"", "empty.pdf")
        self.assertEqual(raised.exception.code, "empty_file")

    def test_rejects_a_non_pdf(self) -> None:
        with self.assertRaises(DocumentError) as raised:
            parse_pdf_bytes(b"this is plain text, not a PDF", "notice.txt")
        self.assertEqual(raised.exception.code, "not_pdf")

    def test_rejects_a_damaged_pdf(self) -> None:
        with self.assertRaises(DocumentError) as raised:
            parse_pdf_bytes(b"%PDF-1.7\nnot a real pdf\n", "damaged.pdf")
        self.assertIn(
            raised.exception.code,
            {"pdf_unreadable", "pdf_no_pages", "pdf_scanned"},
        )


class GuideAndLegalAidTests(unittest.TestCase):
    def test_every_guide_in_every_language(self) -> None:
        for language in LANGUAGES:
            for notice_type in NOTICE_IDS:
                with self.subTest(language=language, notice_type=notice_type):
                    guide = get_guide(notice_type, language)
                    self.assertEqual(guide.language, language)
                    self.assertTrue(guide.title)
                    self.assertTrue(guide.overview)
                    self.assertTrue(guide.native_summary)
                    self.assertTrue(guide.steps)
                    self.assertTrue(guide.documents)
                    self.assertTrue(guide.timeline)
                    self.assertTrue(guide.disclaimer)
                    self.assertIsNone(
                        PLACEHOLDER.search(guide.native_summary),
                        guide.native_summary[:160],
                    )

    def test_legal_aid_directory_and_lookup(self) -> None:
        options = get_legal_aid_options()
        self.assertGreaterEqual(len(options.states), 30)
        self.assertTrue(options.helpline)
        self.assertTrue(options.website)
        maharashtra = next(
            state for state in options.states if state.name == "Maharashtra"
        )
        self.assertIn("Pune", {district.name for district in maharashtra.districts})

        matched = find_legal_aid("Maharashtra", "Pune")
        self.assertTrue(matched.matched)
        self.assertIn("Pune", matched.dlsa_name)
        self.assertEqual(matched.helpline, "15100")
        self.assertTrue(matched.eligibility)
        self.assertTrue(matched.application_steps)

        approximate = find_legal_aid("Maharashtra", "A Made Up District")
        self.assertFalse(approximate.matched)
        self.assertIn("15100", approximate.note)


class ContentFileTests(unittest.TestCase):
    def test_json_data_files_are_valid(self) -> None:
        data_dir = ROOT / "server" / "data"
        for name in ("samples.json", "guides.json", "legal_aid.json"):
            with self.subTest(file=name):
                payload = json.loads((data_dir / name).read_text(encoding="utf-8"))
                self.assertTrue(payload)

    def test_locale_json_files_are_valid(self) -> None:
        locale_dir = ROOT / "server" / "data" / "locales"
        for language in LANGUAGES:
            with self.subTest(language=language):
                payload = json.loads(
                    (locale_dir / f"{language}.json").read_text(encoding="utf-8")
                )
                self.assertIsInstance(payload, dict)
                self.assertIn("notices", payload)


if __name__ == "__main__":
    unittest.main()
