"""France acquisition helpers for an unmodified EspoCRM. No mail transport."""
import argparse
import base64
import csv
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config/france.json").read_text(encoding="utf-8"))
STAGES_BLOCKED = {"Non pertinent", "Ne pas contacter"}
CITIES = {"Lyon": ("45.7640", "4.8357"), "Paris": ("48.8566", "2.3522"), "Lille": ("50.6292", "3.0573"), "Nantes": ("47.2184", "-1.5536"), "Bordeaux": ("44.8378", "-0.5792"), "Strasbourg": ("48.5734", "7.7521")}


def read_env():
    path = ROOT / ".env"
    if not path.exists():
        raise ValueError("Run: python tools/mvp.py init")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def init():
    path = ROOT / ".env"
    if path.exists():
        print("Existing .env preserved.")
        return
    values = {
        "DB_ROOT_PASSWORD": secrets.token_hex(24),
        "DB_PASSWORD": secrets.token_hex(24),
        "CRM_ADMIN_USER": "admin",
        "CRM_ADMIN_PASSWORD": secrets.token_hex(20),
        "CRM_URL": "http://localhost:8080",
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
    print("Local credentials generated in .env; not printed or committed.")


class CRM:
    def __init__(self):
        env = read_env()
        self.url = env["CRM_URL"].rstrip("/") + "/api/v1/"
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Remote CRM requires HTTPS.")
        self.auth = base64.b64encode(
            (env["CRM_ADMIN_USER"] + ":" + env["CRM_ADMIN_PASSWORD"]).encode()
        ).decode()
        # Do not send local CRM authentication through the cloud egress proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, path, data=None):
        body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        request = urllib.request.Request(
            self.url + path, data=body, method=method,
            headers={"Authorization": "Basic " + self.auth, "Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=90) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def leads(self):
        result, offset = [], 0
        while True:
            page = self.call("GET", f"Lead?maxSize=100&offset={offset}&orderBy=id&order=asc")
            rows = page["list"]
            result.extend(rows)
            if len(rows) < 100:
                return result
            offset += len(rows)


def wait_ready(crm, seconds=240):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            crm.call("GET", "App/user")
            return
        except (OSError, json.JSONDecodeError):
            time.sleep(3)
    raise ValueError("CRM not ready; inspect docker compose logs crm db.")


def setup():
    crm = CRM()
    wait_ready(crm)
    existing = crm.call("GET", "Metadata")["entityDefs"]["Lead"]["fields"]
    for field in CONFIG["fields"]:
        name = "c" + field["name"][0].upper() + field["name"][1:]
        if name not in existing:
            crm.call("POST", "Admin/fieldManager/Lead", field)
            print("Created field:", name)
        elif "maxLength" in field and existing[name].get("maxLength") != field["maxLength"]:
            crm.call("PUT", "Admin/fieldManager/Lead/" + name, {"maxLength": field["maxLength"]})
    # Add panels without replacing users' existing fields or layouts.
    for layout_name in ["detail"]:
        layout = crm.call("GET", "Lead/layout/" + layout_name)
        present = set()
        for panel in layout:
            for row in panel.get("rows", []):
                for field in row:
                    if isinstance(field, dict):
                        present.add(field.get("name"))
        fields = ["c" + f["name"][0].upper() + f["name"][1:] for f in CONFIG["fields"]]
        missing = [f for f in fields if f not in present]
        if missing:
            rows = [[{"name": f, "fullWidth": True}] for f in missing]
            layout.append({"customLabel": "法国获客 / Prospection France", "rows": rows})
            crm.call("PUT", "Lead/layout/" + layout_name, layout)
    layout = crm.call("GET", "Lead/layout/list")
    present = {f.get("name") for f in layout}
    for name in ["cReviewStage", "cBuyerSector", "cMachineFamily"]:
        if name not in present:
            layout.append({"name": name, "width": 15})
    crm.call("PUT", "Lead/layout/list", layout)
    print("France fields and layouts ready. Existing configuration preserved.")


def domain(url):
    url = url.strip()
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("Website must be an HTTP(S) address without credentials.")
    host = host.removeprefix("www.")
    if not host or "." not in host or any(c.isspace() for c in host):
        raise ValueError("Invalid website domain.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Use a business domain, not an IP address.")
    return host.encode("idna").decode()


def first(row, *names):
    return next((str(row.get(n) or "").strip() for n in names if str(row.get(n) or "").strip()), "")


def convert_row(row, country, demo=False):
    company = first(row, "company", "title", "accountName")
    if not company:
        raise ValueError("Missing company/title.")
    if len(company) > 255:
        raise ValueError("Company exceeds the CRM's 255-character company field.")
    if company.startswith("DEMO") and not demo:
        raise ValueError("Demo rows require --demo.")
    website = first(row, "website")
    host = domain(website)
    if host.endswith(".example") and not demo:
        raise ValueError("Reserved demonstration domain requires --demo.")
    row_country = first(row, "country") or country
    if row_country.casefold() not in {"france", "fr", "fra"}:
        raise ValueError("Only France is supported by this MVP.")
    values = {
        "lastName": company[:100], "accountName": company, "status": "New",
        "website": website if "://" in website or not website else "https://" + website,
        "addressCountry": "France", "addressCity": first(row, "city"),
        "addressStreet": first(row, "address"),
        "cWebsiteDomain": host, "cSourceUrl": first(row, "source_url", "link"),
        "cEvidenceUrl": first(row, "evidence_url"),
        "cBuyerSector": first(row, "sector"), "cBuyerRole": first(row, "role") or "À vérifier",
        "cMaterials": first(row, "materials"), "cMachineFamily": first(row, "machine") or "À vérifier",
        "cFitReason": first(row, "fit_reason"), "cReviewStage": "À qualifier", "cIsDemo": demo,
        "description": "Imported candidate; country and fit require human review." if not demo else "FICTITIOUS DEMO. Not a real buyer.",
    }
    for key in ["cSourceUrl", "cEvidenceUrl"]:
        if values[key]:
            domain(values[key])
    email = first(row, "email", "emails")
    if email:
        candidates = re.split(r"[;,\s]+", email.strip('[]\"\''))
        email = next((e.strip('\"\'') for e in candidates if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip('\"\''))), "")
        if not email:
            raise ValueError("No valid email in email/emails column.")
        values["emailAddress"] = email
    phone = first(row, "phone", "phoneNumber")
    if phone:
        values["phoneNumber"] = phone
    for field in CONFIG["fields"]:
        key = "c" + field["name"][0].upper() + field["name"][1:]
        if field["type"] == "enum" and values.get(key) is not None and values[key] not in field["options"]:
            raise ValueError("Invalid selection for " + key)
    return values


def lead_keys(lead):
    keys = {"company:" + str(lead.get("accountName") or "").strip().casefold() + ":" + str(lead.get("addressCountry") or "France").casefold()}
    host = lead.get("cWebsiteDomain") or domain(lead.get("website") or "")
    if host:
        keys.add("domain:" + host)
    email = lead.get("emailAddress")
    if email:
        keys.add("email:" + email.casefold())
    return keys


def import_csv(args):
    # Validate the entire file before writing any row.
    with Path(args.file).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"company", "title", "accountName"}.intersection(reader.fieldnames):
            raise ValueError("CSV requires company or title column.")
        rows = []
        for i, row in enumerate(reader, 2):
            try:
                rows.append(convert_row(row, args.country, args.demo))
            except ValueError as error:
                raise ValueError(f"CSV row {i}: {error}") from error
    crm = CRM()
    seen = set()
    for lead in crm.leads():
        seen.update(lead_keys(lead))
    added, duplicate = 0, 0
    for row in rows:
        keys = lead_keys(row)
        if keys & seen:
            duplicate += 1
            continue
        if not args.dry_run:
            crm.call("POST", "Lead", row)
        seen.update(keys)
        added += 1
    print(json.dumps({"dry_run": args.dry_run, "candidates": added, "duplicates_skipped": duplicate}, ensure_ascii=False))


def make_draft(lead):
    if lead.get("cIsDemo"):
        raise ValueError("Demo records cannot generate outreach drafts.")
    if lead.get("cReviewStage") in STAGES_BLOCKED or lead.get("doNotCall") or lead.get("emailAddressIsOptedOut"):
        raise ValueError("Lead is suppressed or unsuitable.")
    if lead.get("cReviewStage") != "À contacter":
        raise ValueError("Review the lead and set follow-up stage to À contacter first.")
    for name in ["cEvidenceUrl", "cFitReason", "cMaterials"]:
        if not lead.get(name):
            raise ValueError("Missing verified field: " + name)
    domain(lead["cEvidenceUrl"])
    machine = lead.get("cMachineFamily")
    if not machine or machine in {"À vérifier", "Autre"}:
        raise ValueError("Select a verified machine family first.")
    subject = "Votre découpe de " + lead["cMaterials"].replace("\n", " ")[:120]
    body = f"""Bonjour,

En consultant les informations publiques de {lead.get('accountName', 'votre entreprise')}, nous avons relevé :
{lead['cFitReason']}
Source : {lead['cEvidenceUrl']}

Nous proposons des solutions de découpe numérique. La gamme {machine} pourrait être à étudier pour vos applications en {lead['cMaterials']}, sous réserve de confirmer les matériaux, épaisseurs, formats et volumes.

Seriez-vous la bonne personne pour discuter de ce sujet ? Si cela vous intéresse, nous pourrions étudier un essai sur vos propres matériaux.

Cordialement,
[Nom du commercial]
[Société et coordonnées réelles]

Si ce sujet ne vous concerne pas ou si vous ne souhaitez plus être contacté, merci de nous le signaler ; nous retirerons vos coordonnées de notre liste de prospection.

BROUILLON À RELIRE : vérifier les faits, la signature et les conditions de contact avant tout envoi.
"""
    return subject, body


def draft(args):
    crm = CRM()
    lead = crm.call("GET", "Lead/" + urllib.parse.quote(args.lead_id, safe=""))
    subject, body = make_draft(lead)
    crm.call("PUT", "Lead/" + lead["id"], {"cDraftSubject": subject, "cDraftBody": body})
    print("French draft saved to the lead. No email was sent.")


def health():
    crm = CRM()
    wait_ready(crm, 15)
    for field in CONFIG["fields"]:
        name = "c" + field["name"][0].upper() + field["name"][1:]
        crm.call("GET", "Admin/fieldManager/Lead/" + name)
    print("CRM authentication and all 13 France fields verified.")


def maps_request(method, path, data=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("http://127.0.0.1:8082/api/v1/" + path, data=body, method=method, headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=30) as response:
        return response.read()


def search(args):
    lat, lon = CITIES[args.city]
    data = {"name": "France: " + args.keyword, "keywords": [args.keyword], "lang": "fr", "zoom": 12, "lat": lat, "lon": lon, "depth": 1, "max_time": 180, "email": False, "fast_mode": False}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        data["proxies"] = [proxy]
    job = json.loads(maps_request("POST", "jobs", data))
    print("Created job:", job["id"])
    print("After completion: python tools/mvp.py download", job["id"])


def download(args):
    job_id = urllib.parse.quote(args.job_id, safe="")
    job = json.loads(maps_request("GET", "jobs/" + job_id))
    status = job.get("status", job.get("Status"))
    if status != "ok":
        raise ValueError("Maps job is not complete: " + str(status))
    raw = maps_request("GET", "jobs/" + job_id + "/download")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows or not all(row.get("title") for row in rows):
        raise ValueError("No usable businesses returned. A job status alone does not prove successful collection.")
    target = Path(args.file or (ROOT / "runtime" / ("maps-" + args.job_id + ".csv")))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as f:
        f.write(raw)
    print(json.dumps({"file": str(target), "businesses": len(rows), "note": "Candidates only; manually verify country and fit."}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ["init", "setup", "health"]:
        subs.add_parser(name)
    imp = subs.add_parser("import")
    imp.add_argument("file")
    imp.add_argument("--country", default="France", help="Fallback only; manually verify search country.")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--demo", action="store_true")
    dra = subs.add_parser("draft")
    dra.add_argument("lead_id")
    sea = subs.add_parser("search")
    sea.add_argument("keyword")
    sea.add_argument("--city", choices=list(CITIES), default="Lyon")
    down = subs.add_parser("download")
    down.add_argument("job_id")
    down.add_argument("--file")
    args = parser.parse_args()
    actions = {"init": init, "setup": setup, "health": health}
    try:
        if args.command in actions:
            actions[args.command]()
        elif args.command == "import":
            import_csv(args)
        elif args.command == "search":
            search(args)
        elif args.command == "download":
            download(args)
        else:
            draft(args)
    except (ValueError, OSError, urllib.error.URLError) as error:
        # HTTP exceptions report status only, never authentication or request bodies.
        print("Operation failed:", str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
