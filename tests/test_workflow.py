import sys
import argparse
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mvp import convert_row, domain, lead_keys, make_draft, download


class WorkflowTests(unittest.TestCase):
    def test_domain_deduplicates_tracking_paths_and_www(self):
        self.assertEqual(domain("https://WWW.Example.fr/products?utm_source=x"), domain("example.fr"))

    def test_website_credentials_rejected(self):
        with self.assertRaises(ValueError):
            domain("https://user:password@example.fr")

    def test_maps_columns_import_without_fabricated_contact(self):
        row = convert_row({"title": "Atelier", "website": "atelier.fr", "emails": "info@atelier.fr;contact@atelier.fr"}, "France")
        self.assertEqual(row["accountName"], "Atelier")
        self.assertEqual(row["cMachineFamily"], "À vérifier")
        self.assertEqual(row["cReviewStage"], "À qualifier")
        self.assertEqual(row["emailAddress"], "info@atelier.fr")

    def test_non_france_import_rejected(self):
        with self.assertRaises(ValueError):
            convert_row({"company": "Atelier", "country": "Belgique"}, "France")

    def test_full_company_name_preserved_when_display_name_is_long(self):
        row = convert_row({"company": "A" * 150}, "France")
        self.assertEqual(len(row["lastName"]), 100)
        self.assertEqual(row["accountName"], "A" * 150)

    def test_demo_requires_explicit_flag(self):
        with self.assertRaises(ValueError):
            convert_row({"company": "DEMO Atelier", "website": "atelier.example"}, "France")

    def test_unknown_machine_rejected_on_import(self):
        with self.assertRaises(ValueError):
            convert_row({"company": "Atelier", "machine": "unverified model"}, "France")

    def test_existing_company_match_without_website(self):
        self.assertTrue(lead_keys({"accountName": "Atelier", "addressCountry": "France"}) & lead_keys({"accountName": " atelier ", "addressCountry": "France"}))

    def candidate(self):
        return {"accountName": "Atelier", "cReviewStage": "À contacter", "cEvidenceUrl": "https://atelier.fr/production", "cFitReason": "Production de prototypes en carton.", "cMaterials": "carton", "cMachineFamily": "PK / PK4"}

    def test_draft_includes_evidence_and_unfilled_identity(self):
        subject, body = make_draft(self.candidate())
        self.assertIn("carton", subject)
        self.assertIn("https://atelier.fr/production", body)
        self.assertIn("[Société et coordonnées réelles]", body)
        self.assertIn("ne souhaitez plus être contacté", body)

    def test_unreviewed_or_suppressed_leads_cannot_get_drafts(self):
        for stage in ["À qualifier", "Ne pas contacter", "Non pertinent", "Contacté"]:
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                make_draft(dict(self.candidate(), cReviewStage=stage))

    def test_demo_cannot_get_draft(self):
        with self.assertRaises(ValueError):
            make_draft(dict(self.candidate(), cIsDemo=True))

    def test_opted_out_lead_cannot_get_draft(self):
        with self.assertRaises(ValueError):
            make_draft(dict(self.candidate(), emailAddressIsOptedOut=True))

    def test_missing_evidence_cannot_get_draft(self):
        for field in ["cEvidenceUrl", "cFitReason", "cMaterials", "cMachineFamily"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_draft(dict(self.candidate(), **{field: ""}))

    def test_maps_ok_with_empty_csv_is_not_success(self):
        with patch("mvp.maps_request", side_effect=[b'{"Status":"ok"}', b'title,website\n']):
            with self.assertRaisesRegex(ValueError, "No usable businesses"):
                download(argparse.Namespace(job_id="test", file=None))

    def test_incomplete_maps_job_cannot_download(self):
        with patch("mvp.maps_request", return_value=b'{"Status":"running"}'):
            with self.assertRaisesRegex(ValueError, "not complete"):
                download(argparse.Namespace(job_id="test", file=None))


if __name__ == "__main__":
    unittest.main()
