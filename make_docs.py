"""Generate the synthetic documents for the reproduction.

Writes docs/<name>.txt and docs/manifest.json ({file: correspondent or null}).
The target document (target.txt) is uploaded WITHOUT a correspondent; its
expected correspondent is "Acme Domains", which has exactly one earlier,
nearly identical invoice.
"""

from __future__ import annotations

import json
import pathlib
import random

random.seed(42)
out = pathlib.Path(__file__).parent / "docs"
out.mkdir(exist_ok=True)
manifest = {}

CUSTOMER = """Bill to: John Example
12 Sample Street, Springfield 75001
Customer ID: 000123456"""


def invoice(issuer, issuer_addr, email, number, date, items, paid_date):
    net = sum(p for _, p in items)
    vat = round(net * 0.18, 2)
    lines = "\n".join(f"{desc} | 1 | {p:.2f} | {p:.2f}" for desc, p in items)
    return f"""{issuer}
{issuer_addr}
{email}
Date: {date}
Original
Tax Invoice / Receipt No. {number}
{CUSTOMER}
Description | Qty | Price | Total
{lines}
Total before discount: {net:.2f}
Total before VAT: {net:.2f}
VAT 18%: {vat:.2f}
Total to pay: {net + vat:.2f}
Payments
Amount | Method | Date | Reference
{net + vat:.2f} | Visa | {paid_date} | 0
Total paid: {net + vat:.2f}
Customer signature:
Issuer signature:
"""


def write(name, text, correspondent):
    (out / f"{name}.txt").write_text(text)
    manifest[f"{name}.txt"] = correspondent


ACME = ("Acme Domains Ltd.", "4 Registrar Road, Example City 10001", "billing@acmedomains.example")

# The one earlier invoice from the correct correspondent: same template, previous year.
write("acme-2025", invoice(*ACME, "2025-0417", "18/10/25",
      [("Domain renewal for one year: example-family.org", 77.97)], "18/10/25"), "Acme Domains")

# Distractors: same invoice template, same customer, different issuers/services.
DISTRACTORS = [
    ("Northwind Tracking", 7, ("Northwind Vehicle Tracking Ltd.", "88 Fleet Avenue, Example City 4400", "invoices@northwind.example"),
     "Vehicle tracking subscription, monthly fee", 39.90),
    ("Contoso Mobile", 4, ("Contoso Mobile Ltd.", "1 Cellular Plaza, Example City 5100", "billing@contoso-mobile.example"),
     "Mobile line plan, monthly", 29.90),
    ("Fabrikam Internet", 4, ("Fabrikam Internet Services Ltd.", "7 Fiber Lane, Example City 6200", "billing@fabrikam.example"),
     "Internet access + fixed IP, monthly", 99.00),
]
for corr, count, issuer, desc, price in DISTRACTORS:
    for i in range(count):
        month = (i % 12) + 1
        write(f"{corr.split()[0].lower()}-{i + 1}",
              invoice(*issuer, str(9000000 + random.randint(0, 999999)), f"0{month % 9 + 1}/{month:02d}/26",
                      [(desc, price)], f"0{month % 9 + 1}/{month:02d}/26"), corr)

# Unrelated documents so the index is not trivially small.
MISC = [
    ("Springfield Clinic", "Referral letter\nPatient: John Example\nPlease see the patient for a routine cardiology check-up.\nDr. A. Sample"),
    ("Springfield Clinic", "Prescription\nPatient: John Example\nAmoxicillin 500mg, three times daily for 7 days."),
    ("City of Springfield", "Municipal property tax notice\nAccount 1234567\nPeriod: 01/2026-02/2026\nAmount due: 1,240.00"),
    ("City of Springfield", "Parking permit renewal\nPermit holder: John Example\nValid until 31/12/2026"),
    ("Example Insurance", "Home insurance policy schedule\nPolicy 55-1234\nInsured: John Example\nAnnual premium: 2,310.00"),
    ("Example Insurance", "Car insurance renewal notice\nPolicy 77-9876\nRenewal date: 01/03/2026"),
    ("Springfield Bank", "Account statement\nAccount holder: John Example\nOpening balance 10,000.00\nClosing balance 9,512.33"),
    ("Springfield Bank", "Credit card statement\nCard ending 4242\nTotal charges this month: 4,118.20"),
]
for i, (corr, text) in enumerate(MISC):
    write(f"misc-{i + 1}", text + "\n", corr)

# The new document: next year's invoice from Acme Domains, uploaded without a correspondent.
write("target", invoice(*ACME, "2026-0388", "18/10/26",
      [("Domain renewal for one year: example-family.org", 77.97)], "18/10/26"), None)

(out / "manifest.json").write_text(json.dumps(manifest, indent=1))
print(f"wrote {len(manifest)} documents to {out}")
