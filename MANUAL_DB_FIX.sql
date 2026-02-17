-- HerCare manual DB fix (safe to run multiple times)
-- Run in Supabase SQL Editor or PostgreSQL client.

BEGIN;

-- Needed for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1) doctor_patient_links table (create if missing)
CREATE TABLE IF NOT EXISTS doctor_patient_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  patient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permissions JSON DEFAULT '{}'::json,
  share_code VARCHAR UNIQUE,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doctor_patient_links_doctor_id ON doctor_patient_links(doctor_id);
CREATE INDEX IF NOT EXISTS idx_doctor_patient_links_patient_id ON doctor_patient_links(patient_id);

-- Add missing columns if table exists but is old
ALTER TABLE doctor_patient_links
  ADD COLUMN IF NOT EXISTS permissions JSON DEFAULT '{}'::json;
ALTER TABLE doctor_patient_links
  ADD COLUMN IF NOT EXISTS share_code VARCHAR;
ALTER TABLE doctor_patient_links
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

-- 2) consultations table (create if missing)
CREATE TABLE IF NOT EXISTS consultations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  patient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  visit_date DATE NOT NULL DEFAULT CURRENT_DATE,
  symptoms TEXT,
  diagnosis TEXT,
  treatment_plan TEXT,
  prescriptions JSON,
  billing_items JSON,
  total_amount DOUBLE PRECISION DEFAULT 0,
  payment_status VARCHAR DEFAULT 'pending',
  prescription_text TEXT,
  notes TEXT,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consultations_doctor_id ON consultations(doctor_id);
CREATE INDEX IF NOT EXISTS idx_consultations_patient_id ON consultations(patient_id);
CREATE INDEX IF NOT EXISTS idx_consultations_visit_date ON consultations(visit_date);

-- Add missing columns if table exists but is old
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS treatment_plan TEXT;
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS prescriptions JSON;
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS billing_items JSON;
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS total_amount DOUBLE PRECISION DEFAULT 0;
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS payment_status VARCHAR DEFAULT 'pending';
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS prescription_text TEXT;
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE consultations
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

COMMIT;

-- Quick checks (run after COMMIT)
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'doctor_patient_links' ORDER BY ordinal_position;
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'consultations' ORDER BY ordinal_position;
