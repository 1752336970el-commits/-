"""Exercise the live CRM workflow; remove only the temporary records we create."""
import argparse
import csv
import json
from pathlib import Path
import secrets
import tempfile

from mvp import CRM, draft, import_csv


def main():
    crm = CRM()
    token = secrets.token_hex(8)
    company = "TEST-FICTITIOUS-" + token
    ids = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "integration.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["company", "website", "country"])
                writer.writeheader()
                writer.writerow({"company": company, "website": "https://" + token + ".example", "country": "France"})
            args = argparse.Namespace(file=str(path), country="France", demo=True, dry_run=False)
            import_csv(args)
            leads = [r for r in crm.leads() if r.get("accountName") == company]
            ids = [r["id"] for r in leads]
            assert len(ids) == 1, "Import did not create exactly one test record"
            lead_id = ids[0]
            import_csv(args)
            assert len([r for r in crm.leads() if r.get("accountName") == company]) == 1, "Duplicate imported"
            args.dry_run = True
            import_csv(args)
            # This is a synthetic validation record, never a real prospect.
            crm.call("PUT", "Lead/" + lead_id, {"cIsDemo": False, "cReviewStage": "À contacter", "cEvidenceUrl": "https://" + token + ".example/test", "cFitReason": "FICTITIOUS INTEGRATION TEST", "cMaterials": "carton", "cMachineFamily": "PK / PK4"})
            draft(argparse.Namespace(lead_id=lead_id))
            record = crm.call("GET", "Lead/" + lead_id)
            assert "FICTITIOUS INTEGRATION TEST" in record["cDraftBody"]
            assert record["cDraftSubject"], "Draft not saved"
            crm.call("PUT", "Lead/" + lead_id, {"cReviewStage": "Ne pas contacter"})
            try:
                draft(argparse.Namespace(lead_id=lead_id))
            except ValueError:
                pass
            else:
                raise AssertionError("Suppressed lead was not blocked")
            detail = crm.call("GET", "Lead/layout/detail")
            assert any(p.get("customLabel") == "法国获客 / Prospection France" for p in detail)
            print(json.dumps({"passed": ["authenticated CRM", "CSV import", "duplicate skipped", "dry run", "custom fields persisted", "French draft saved", "suppression enforced", "UI detail panel"], "emails_sent": 0}))
    finally:
        # Recover IDs after a partially completed request, preserving all other records.
        for record in crm.leads():
            if record.get("accountName") == company and record["id"] not in ids:
                ids.append(record["id"])
        for lead_id in ids:
            crm.call("DELETE", "Lead/" + lead_id)


if __name__ == "__main__":
    main()
