#!/usr/bin/env python3
"""
Live smoke test for HerCare production API.

Usage:
  python3 live_smoke_test.py
  BASE_URL=http://... python3 live_smoke_test.py
"""

import json
import os
import sys
import time
from datetime import date

import requests

BASE = os.getenv("BASE_URL", "http://ec2-43-204-138-153.ap-south-1.compute.amazonaws.com")
FRONT_ORIGIN = os.getenv(
    "FRONT_ORIGIN",
    "http://hercare-app-frontend-cszaiz.s3-website.ap-south-1.amazonaws.com",
)


def ok(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"{status} - {name} {detail}".rstrip())
    return cond


def post(path: str, **kw):
    return requests.post(BASE + path, timeout=25, **kw)


def get(path: str, **kw):
    return requests.get(BASE + path, timeout=25, **kw)


def main() -> int:
    all_ok = True
    stamp = str(int(time.time()))
    doc_email = f"doc_{stamp}@example.com"
    real_email = f"real_{stamp}@example.com"
    password = "Test@123456"

    # 1) health
    r = get("/")
    all_ok &= ok("Health root", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return 2

    # 2) doctor register
    r = post(
        "/api/v1/auth/register",
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {
                "name": "Dr Smoke",
                "email": doc_email,
                "password": password,
                "age": 35,
                "role": "doctor",
            }
        ),
    )
    all_ok &= ok("Doctor register", r.status_code == 201, f"status={r.status_code}")
    if r.status_code != 201:
        print(r.text)
        return 2
    d = r.json()
    doc_id = d["id"]
    doc_token = d.get("access_token")
    all_ok &= ok("Doctor token present", bool(doc_token))

    # 3) doctor login
    r = post(
        "/api/v1/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": doc_email, "password": password}),
    )
    all_ok &= ok("Doctor login", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        doc_token = r.json().get("access_token", doc_token)

    # 4) create shadow patient via doctor
    r = post(
        "/register-patient",
        headers={"Authorization": f"Bearer {doc_token}", "Content-Type": "application/json"},
        data=json.dumps({"name": "Shadow User", "age": 22}),
    )
    all_ok &= ok("Doctor creates shadow patient", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        print(r.text)
        return 2
    shadow = r.json()
    shadow_id = shadow["patient_id"]
    share_code = shadow.get("share_code")
    all_ok &= ok("Share code present", bool(share_code), f"code={share_code}")

    # 5) doctor patient list
    r = get(f"/my-patients/{doc_id}", headers={"Authorization": f"Bearer {doc_token}"})
    all_ok &= ok("Doctor patient list", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        arr = r.json()
        found = any(p.get("patient_id") == shadow_id for p in arr)
        all_ok &= ok("Shadow patient appears", found, f"count={len(arr)}")

    # 6) create consultation for shadow patient
    payload = {
        "doctor_id": doc_id,
        "patient_id": shadow_id,
        "visit_date": str(date.today()),
        "symptoms": "cough",
        "diagnosis": "viral",
        "treatment_plan": "saline",
        "prescriptions": [{"name": "cet", "dosage": "5", "timing": "Twice Daily", "duration": "5 days"}],
        "billing_items": [{"service": "test", "cost": 500}],
        "total_amount": 500,
    }
    r = post(
        "/consultations",
        headers={"Authorization": f"Bearer {doc_token}", "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    all_ok &= ok("Create consultation", r.status_code == 200, f"status={r.status_code}")

    # 7) register real patient
    r = post(
        "/api/v1/auth/register",
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {
                "name": "Real User",
                "email": real_email,
                "password": password,
                "age": 23,
                "role": "patient",
            }
        ),
    )
    all_ok &= ok("Real patient register", r.status_code == 201, f"status={r.status_code}")
    if r.status_code != 201:
        print(r.text)
        return 2
    real = r.json()
    real_id = real["id"]
    real_token = real.get("access_token")

    # 8) link shadow record to real patient
    r = post(f"/patients/link?share_code={share_code}", headers={"Authorization": f"Bearer {real_token}"})
    all_ok &= ok("Link shadow records", r.status_code == 200, f"status={r.status_code}")

    # 9) get consultations after linking
    r = get(f"/consultations/{real_id}", headers={"Authorization": f"Bearer {real_token}"})
    all_ok &= ok("Fetch consultations", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        arr = r.json()
        all_ok &= ok("Consultation exists", len(arr) >= 1, f"count={len(arr)}")

    # 10) CORS preflight for critical route
    r = requests.options(
        BASE + "/consultations",
        timeout=25,
        headers={
            "Origin": FRONT_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    all_ok &= ok("CORS preflight consultations", r.status_code == 200, f"status={r.status_code}")

    print("\nOVERALL", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
