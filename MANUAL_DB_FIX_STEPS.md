# Manual DB Fix Steps (Beginner Friendly)

Use this when the app shows errors like:
- `Failed to fetch ... /consultations`
- `column ... does not exist`
- `table ... does not exist`

## 1) Open your database SQL editor
- If you use Supabase:
  - Go to Supabase Dashboard
  - Open your project
  - Click `SQL Editor`
  - Click `New query`

## 2) Run the fix script
- Open this file from project:
  - `hercare-backend/MANUAL_DB_FIX.sql`
- Copy full SQL
- Paste in SQL Editor
- Click `Run`

## 3) Confirm it worked
Run these 2 queries:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'doctor_patient_links'
ORDER BY ordinal_position;
```

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'consultations'
ORDER BY ordinal_position;
```

You should see:
- `doctor_patient_links.share_code`
- `consultations.treatment_plan`
- `consultations.prescriptions`
- `consultations.billing_items`
- `consultations.total_amount`
- `consultations.payment_status`

## 4) Restart backend
If your backend is on EC2 + Docker, restart container:

```bash
sudo docker restart $(sudo docker ps -q | head -n 1)
```

## 5) Test again in app
- Hard refresh browser: `Ctrl/Cmd + Shift + R`
- Login again
- Re-test patient registration and consultation save

## Why this error comes
This happens when app code is updated but database schema is still old.
The API tries to write into a new column (example: `treatment_plan`), but DB does not have that column yet.

## Rule for future
Every time backend model changes:
1. Run DB migration SQL first
2. Deploy backend code second
3. Test critical flows (register patient, save consultation)
