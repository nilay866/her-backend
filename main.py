from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.orm import Session
from database import get_db
from models import User, HealthLog, PregnancyProfile, DoctorProfile, DoctorPatientLink, MedicalReport, Medication, DietPlan, EmergencyRequest
from jose import jwt, JWTError
import bcrypt
from pydantic import BaseModel
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
from typing import Optional, List
import uuid, os, random, string

load_dotenv()

app = FastAPI(title="HerCare API")

# ────── CORS ──────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://ec2-52-66-232-144.ap-south-1.compute.amazonaws.com",
        "https://nilay866.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ────── JWT Security ──────
SECRET_KEY = os.getenv("SECRET_KEY", "hercare-fallback-secret")
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: str, name: str) -> str:
    return jwt.encode({"sub": user_id, "name": name, "exp": datetime.utcnow() + timedelta(days=30)}, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(authorization: str) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    try:
        return jwt.decode(authorization[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ────── Schemas ──────
class HealthLogCreate(BaseModel):
    user_id: str
    log_type: str = "health_check"
    pain_level: int = 0
    bleeding_level: str = "light"
    mood: str = "neutral"
    notes: str = ""

class HealthLogUpdate(BaseModel):
    log_type: str | None = None
    pain_level: int | None = None
    bleeding_level: str | None = None
    mood: str | None = None
    notes: str | None = None

class ChatRequest(BaseModel):
    message: str

class SymptomRequest(BaseModel):
    symptoms: str

# ════════════════════════════════════
#               ROUTES
# ════════════════════════════════════

@app.get("/")
def home():
    return {"message": "HerCare API Running"}

# ────── Auth ──────
@app.post("/register")
def register(name: str, email: str, password: str, age: int = 25, role: str = "patient", db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(id=uuid.uuid4(), name=name, email=email, password_hash=hash_password(password), age=age, role=role)
    db.add(user); db.commit(); db.refresh(user)
    return {"message": "User registered", "id": str(user.id), "name": user.name, "token": create_token(str(user.id), user.name)}

@app.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash or not check_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"message": "Login successful", "id": str(user.id), "name": user.name, "token": create_token(str(user.id), user.name)}

@app.get("/me")
def get_me(authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    user = db.query(User).filter(User.id == uuid.UUID(payload["sub"])).first()
    if not user: raise HTTPException(status_code=404, detail="User not found")
    return {"id": str(user.id), "name": user.name, "email": user.email, "age": user.age, "role": user.role}

# ────── Legacy ──────
@app.post("/create-user")
def create_user(name: str, age: int = 25, role: str = "patient", db: Session = Depends(get_db)):
    user = User(id=uuid.uuid4(), name=name, age=age, role=role)
    db.add(user); db.commit(); db.refresh(user)
    return {"message": "User created", "id": str(user.id)}

# ════════════════════════════════════
#        PREGNANCY PROFILE
# ════════════════════════════════════

class PregnancyProfileCreate(BaseModel):
    user_id: str
    last_period_date: str  # "YYYY-MM-DD"
    pregnancy_type: str = "continue"  # "continue" or "abort"
    blood_group: str | None = None
    weight: float | None = None
    height: float | None = None
    existing_conditions: str | None = None

class PregnancyProfileUpdate(BaseModel):
    pregnancy_type: str | None = None
    blood_group: str | None = None
    weight: float | None = None
    height: float | None = None
    existing_conditions: str | None = None

def _pregnancy_response(p):
    lmp = p.last_period_date
    today = date.today()
    days = (today - lmp).days
    weeks = days // 7
    trimester = 1 if weeks <= 12 else (2 if weeks <= 27 else 3)
    return {
        "id": str(p.id), "user_id": str(p.user_id),
        "last_period_date": str(p.last_period_date), "due_date": str(p.due_date),
        "pregnancy_type": p.pregnancy_type, "blood_group": p.blood_group,
        "weight": p.weight, "height": p.height,
        "existing_conditions": p.existing_conditions,
        "gestational_weeks": weeks, "gestational_days": days % 7,
        "trimester": trimester,
    }

@app.post("/pregnancy-profile")
def create_pregnancy_profile(body: PregnancyProfileCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    existing = db.query(PregnancyProfile).filter(PregnancyProfile.user_id == uuid.UUID(body.user_id)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Profile already exists. Use PUT to update.")
    lmp = datetime.strptime(body.last_period_date, "%Y-%m-%d").date()
    due = lmp + timedelta(days=280)
    profile = PregnancyProfile(
        id=uuid.uuid4(), user_id=uuid.UUID(body.user_id),
        last_period_date=lmp, due_date=due,
        pregnancy_type=body.pregnancy_type, blood_group=body.blood_group,
        weight=body.weight, height=body.height, existing_conditions=body.existing_conditions
    )
    db.add(profile); db.commit(); db.refresh(profile)
    return _pregnancy_response(profile)

@app.get("/pregnancy-profile/{user_id}")
def get_pregnancy_profile(user_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    profile = db.query(PregnancyProfile).filter(PregnancyProfile.user_id == uuid.UUID(user_id)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No pregnancy profile found")
    return _pregnancy_response(profile)

@app.put("/pregnancy-profile/{user_id}")
def update_pregnancy_profile(user_id: str, body: PregnancyProfileUpdate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    profile = db.query(PregnancyProfile).filter(PregnancyProfile.user_id == uuid.UUID(user_id)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No pregnancy profile found")
    if body.pregnancy_type is not None: profile.pregnancy_type = body.pregnancy_type
    if body.blood_group is not None: profile.blood_group = body.blood_group
    if body.weight is not None: profile.weight = body.weight
    if body.height is not None: profile.height = body.height
    if body.existing_conditions is not None: profile.existing_conditions = body.existing_conditions
    db.commit(); db.refresh(profile)
    return _pregnancy_response(profile)

# ════════════════════════════════════
#        DOCTOR PROFILE & LINKING
# ════════════════════════════════════

class DoctorProfileCreate(BaseModel):
    user_id: str
    specialization: str | None = None
    hospital: str | None = None
    experience_years: int | None = None

class LinkDoctorRequest(BaseModel):
    patient_id: str
    invite_code: str

@app.post("/doctor-profile")
def create_doctor_profile(body: DoctorProfileCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    profile = DoctorProfile(
        id=uuid.uuid4(), user_id=uuid.UUID(body.user_id),
        specialization=body.specialization, hospital=body.hospital,
        experience_years=body.experience_years, invite_code=code
    )
    db.add(profile); db.commit(); db.refresh(profile)
    return {"id": str(profile.id), "user_id": str(profile.user_id),
            "specialization": profile.specialization, "hospital": profile.hospital,
            "invite_code": profile.invite_code}

@app.get("/doctor-profile/{user_id}")
def get_doctor_profile(user_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == uuid.UUID(user_id)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    return {"id": str(profile.id), "user_id": str(profile.user_id),
            "specialization": profile.specialization, "hospital": profile.hospital,
            "experience_years": profile.experience_years, "invite_code": profile.invite_code,
            "available": profile.available}

@app.post("/link-doctor")
def link_doctor(body: LinkDoctorRequest, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    doctor_profile = db.query(DoctorProfile).filter(DoctorProfile.invite_code == body.invite_code).first()
    if not doctor_profile:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    existing = db.query(DoctorPatientLink).filter(
        DoctorPatientLink.doctor_id == doctor_profile.user_id,
        DoctorPatientLink.patient_id == uuid.UUID(body.patient_id)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already linked")
    link = DoctorPatientLink(id=uuid.uuid4(), doctor_id=doctor_profile.user_id, patient_id=uuid.UUID(body.patient_id))
    db.add(link); db.commit()
    doctor_user = db.query(User).filter(User.id == doctor_profile.user_id).first()
    return {"message": "Linked successfully", "doctor_name": doctor_user.name if doctor_user else "Doctor",
            "specialization": doctor_profile.specialization}

@app.get("/my-doctor/{patient_id}")
def get_my_doctor(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    link = db.query(DoctorPatientLink).filter(DoctorPatientLink.patient_id == uuid.UUID(patient_id)).first()
    if not link:
        return {"linked": False}
    doctor = db.query(User).filter(User.id == link.doctor_id).first()
    doc_profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == link.doctor_id).first()
    return {"linked": True, "doctor_id": str(link.doctor_id), "doctor_name": doctor.name if doctor else "Doctor",
            "specialization": doc_profile.specialization if doc_profile else None,
            "hospital": doc_profile.hospital if doc_profile else None}

@app.get("/my-patients/{doctor_id}")
def get_my_patients(doctor_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    links = db.query(DoctorPatientLink).filter(DoctorPatientLink.doctor_id == uuid.UUID(doctor_id)).all()
    patients = []
    for link in links:
        patient = db.query(User).filter(User.id == link.patient_id).first()
        pregnancy = db.query(PregnancyProfile).filter(PregnancyProfile.user_id == link.patient_id).first()
        patients.append({
            "patient_id": str(link.patient_id), "name": patient.name if patient else "Patient",
            "age": patient.age if patient else None,
            "pregnancy_type": pregnancy.pregnancy_type if pregnancy else None,
            "gestational_weeks": ((date.today() - pregnancy.last_period_date).days // 7) if pregnancy else None,
        })
    return patients

# ════════════════════════════════════
#          MEDICAL REPORTS
# ════════════════════════════════════

class ReportCreate(BaseModel):
    patient_id: str
    uploaded_by: str
    title: str
    report_type: str = "other"
    notes: str | None = None
    file_data: str | None = None
    file_name: str | None = None

@app.post("/reports")
def create_report(body: ReportCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    report = MedicalReport(
        id=uuid.uuid4(), patient_id=uuid.UUID(body.patient_id), uploaded_by=uuid.UUID(body.uploaded_by),
        title=body.title, report_type=body.report_type, notes=body.notes,
        file_data=body.file_data, file_name=body.file_name
    )
    db.add(report); db.commit(); db.refresh(report)
    return {"id": str(report.id), "title": report.title, "report_type": report.report_type,
            "notes": report.notes, "file_name": report.file_name, "created_at": str(report.created_at)}

@app.get("/reports/{patient_id}")
def get_reports(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    reports = db.query(MedicalReport).filter(MedicalReport.patient_id == uuid.UUID(patient_id)).order_by(MedicalReport.created_at.desc()).all()
    return [{"id": str(r.id), "title": r.title, "report_type": r.report_type, "notes": r.notes,
             "file_name": r.file_name, "uploaded_by": str(r.uploaded_by), "created_at": str(r.created_at)} for r in reports]

@app.delete("/reports/{report_id}")
def delete_report(report_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    report = db.query(MedicalReport).filter(MedicalReport.id == uuid.UUID(report_id)).first()
    if not report: raise HTTPException(status_code=404, detail="Report not found")
    db.delete(report); db.commit()
    return {"message": "Report deleted"}

# ════════════════════════════════════
#          MEDICATIONS
# ════════════════════════════════════

class MedicationCreate(BaseModel):
    patient_id: str
    prescribed_by: str | None = None
    name: str
    dosage: str | None = None
    frequency: str | None = None
    times: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    notes: str | None = None

class MedicationUpdate(BaseModel):
    name: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    times: list[str] | None = None
    end_date: str | None = None
    notes: str | None = None
    active: bool | None = None

@app.post("/medications")
def create_medication(body: MedicationCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    med = Medication(
        id=uuid.uuid4(), patient_id=uuid.UUID(body.patient_id),
        prescribed_by=uuid.UUID(body.prescribed_by) if body.prescribed_by else None,
        name=body.name, dosage=body.dosage, frequency=body.frequency, times=body.times,
        start_date=datetime.strptime(body.start_date, "%Y-%m-%d").date() if body.start_date else date.today(),
        end_date=datetime.strptime(body.end_date, "%Y-%m-%d").date() if body.end_date else None,
        notes=body.notes
    )
    db.add(med); db.commit(); db.refresh(med)
    return {"id": str(med.id), "name": med.name, "dosage": med.dosage, "frequency": med.frequency,
            "times": med.times, "start_date": str(med.start_date), "end_date": str(med.end_date) if med.end_date else None,
            "notes": med.notes, "active": med.active}

@app.get("/medications/{patient_id}")
def get_medications(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    meds = db.query(Medication).filter(Medication.patient_id == uuid.UUID(patient_id), Medication.active == True).all()
    return [{"id": str(m.id), "name": m.name, "dosage": m.dosage, "frequency": m.frequency,
             "times": m.times, "start_date": str(m.start_date), "end_date": str(m.end_date) if m.end_date else None,
             "notes": m.notes, "active": m.active} for m in meds]

@app.put("/medications/{med_id}")
def update_medication(med_id: str, body: MedicationUpdate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    med = db.query(Medication).filter(Medication.id == uuid.UUID(med_id)).first()
    if not med: raise HTTPException(status_code=404, detail="Medication not found")
    if body.name is not None: med.name = body.name
    if body.dosage is not None: med.dosage = body.dosage
    if body.frequency is not None: med.frequency = body.frequency
    if body.times is not None: med.times = body.times
    if body.end_date is not None: med.end_date = datetime.strptime(body.end_date, "%Y-%m-%d").date()
    if body.notes is not None: med.notes = body.notes
    if body.active is not None: med.active = body.active
    db.commit(); db.refresh(med)
    return {"id": str(med.id), "name": med.name, "dosage": med.dosage, "active": med.active}

@app.delete("/medications/{med_id}")
def delete_medication(med_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    med = db.query(Medication).filter(Medication.id == uuid.UUID(med_id)).first()
    if not med: raise HTTPException(status_code=404, detail="Medication not found")
    db.delete(med); db.commit()
    return {"message": "Medication deleted"}

# ════════════════════════════════════
#          DIET PLANS
# ════════════════════════════════════

class DietPlanCreate(BaseModel):
    patient_id: str
    created_by: str | None = None
    meal_type: str  # "breakfast", "lunch", "snack", "dinner"
    food_items: str
    calories: int | None = None
    notes: str | None = None
    day_of_week: str | None = None

@app.post("/diet-plans")
def create_diet_plan(body: DietPlanCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    plan = DietPlan(
        id=uuid.uuid4(), patient_id=uuid.UUID(body.patient_id),
        created_by=uuid.UUID(body.created_by) if body.created_by else None,
        meal_type=body.meal_type, food_items=body.food_items,
        calories=body.calories, notes=body.notes, day_of_week=body.day_of_week
    )
    db.add(plan); db.commit(); db.refresh(plan)
    return {"id": str(plan.id), "meal_type": plan.meal_type, "food_items": plan.food_items,
            "calories": plan.calories, "notes": plan.notes, "day_of_week": plan.day_of_week}

@app.get("/diet-plans/{patient_id}")
def get_diet_plans(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    plans = db.query(DietPlan).filter(DietPlan.patient_id == uuid.UUID(patient_id)).all()
    return [{"id": str(p.id), "meal_type": p.meal_type, "food_items": p.food_items,
             "calories": p.calories, "notes": p.notes, "day_of_week": p.day_of_week} for p in plans]

@app.put("/diet-plans/{plan_id}")
def update_diet_plan(plan_id: str, body: DietPlanCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    plan = db.query(DietPlan).filter(DietPlan.id == uuid.UUID(plan_id)).first()
    if not plan: raise HTTPException(status_code=404, detail="Diet plan not found")
    plan.meal_type = body.meal_type
    plan.food_items = body.food_items
    if body.calories is not None: plan.calories = body.calories
    if body.notes is not None: plan.notes = body.notes
    if body.day_of_week is not None: plan.day_of_week = body.day_of_week
    db.commit(); db.refresh(plan)
    return {"id": str(plan.id), "meal_type": plan.meal_type, "food_items": plan.food_items}

@app.delete("/diet-plans/{plan_id}")
def delete_diet_plan(plan_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    plan = db.query(DietPlan).filter(DietPlan.id == uuid.UUID(plan_id)).first()
    if not plan: raise HTTPException(status_code=404, detail="Diet plan not found")
    db.delete(plan); db.commit()
    return {"message": "Diet plan deleted"}

# ════════════════════════════════════
#        EMERGENCY CONSULTATION
# ════════════════════════════════════

class EmergencyCreate(BaseModel):
    patient_id: str
    message: str

@app.post("/emergency")
def create_emergency(body: EmergencyCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    req = EmergencyRequest(id=uuid.uuid4(), patient_id=uuid.UUID(body.patient_id), message=body.message)
    db.add(req); db.commit(); db.refresh(req)
    return {"id": str(req.id), "status": req.status, "message": req.message, "created_at": str(req.created_at)}

@app.get("/emergencies/pending")
def get_pending_emergencies(authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    reqs = db.query(EmergencyRequest).filter(EmergencyRequest.status == "pending").order_by(EmergencyRequest.created_at.desc()).all()
    result = []
    for r in reqs:
        patient = db.query(User).filter(User.id == r.patient_id).first()
        result.append({"id": str(r.id), "patient_id": str(r.patient_id),
                       "patient_name": patient.name if patient else "Patient",
                       "message": r.message, "created_at": str(r.created_at)})
    return result

@app.get("/emergencies/{patient_id}")
def get_my_emergencies(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    reqs = db.query(EmergencyRequest).filter(EmergencyRequest.patient_id == uuid.UUID(patient_id)).order_by(EmergencyRequest.created_at.desc()).all()
    return [{"id": str(r.id), "message": r.message, "status": r.status,
             "consultation_type": r.consultation_type, "created_at": str(r.created_at)} for r in reqs]

@app.put("/emergency/{emergency_id}/accept")
def accept_emergency(emergency_id: str, consultation_type: str = "online", authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    req = db.query(EmergencyRequest).filter(EmergencyRequest.id == uuid.UUID(emergency_id)).first()
    if not req: raise HTTPException(status_code=404, detail="Emergency not found")
    req.status = "accepted"
    req.accepted_by = uuid.UUID(payload["sub"])
    req.consultation_type = consultation_type
    db.commit(); db.refresh(req)
    return {"id": str(req.id), "status": req.status, "consultation_type": req.consultation_type}

@app.put("/emergency/{emergency_id}/resolve")
def resolve_emergency(emergency_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    req = db.query(EmergencyRequest).filter(EmergencyRequest.id == uuid.UUID(emergency_id)).first()
    if not req: raise HTTPException(status_code=404, detail="Emergency not found")
    req.status = "resolved"
    db.commit()
    return {"id": str(req.id), "status": "resolved"}

# ════════════════════════════════════
#           HEALTH LOGS CRUD
# ════════════════════════════════════

@app.post("/health-logs")
def create_health_log(body: HealthLogCreate, db: Session = Depends(get_db)):
    log = HealthLog(id=uuid.uuid4(), user_id=uuid.UUID(body.user_id), log_type=body.log_type, title=body.log_type,
                    pain_level=body.pain_level, bleeding_level=body.bleeding_level, mood=body.mood, notes=body.notes, log_date=date.today())
    db.add(log); db.commit(); db.refresh(log)
    return {"id": str(log.id), "user_id": str(log.user_id), "log_type": log.log_type, "pain_level": log.pain_level,
            "bleeding_level": log.bleeding_level, "mood": log.mood, "notes": log.notes, "log_date": str(log.log_date)}

@app.get("/health-logs")
def get_health_logs(user_id: str, db: Session = Depends(get_db)):
    logs = db.query(HealthLog).filter(HealthLog.user_id == uuid.UUID(user_id)).order_by(HealthLog.log_date.desc()).all()
    return [{"id": str(l.id), "user_id": str(l.user_id), "log_type": l.log_type, "pain_level": l.pain_level,
             "bleeding_level": l.bleeding_level, "mood": l.mood, "notes": l.notes, "log_date": str(l.log_date)} for l in logs]

@app.put("/health-logs/{log_id}")
def update_health_log(log_id: str, body: HealthLogUpdate, db: Session = Depends(get_db)):
    log = db.query(HealthLog).filter(HealthLog.id == uuid.UUID(log_id)).first()
    if not log: raise HTTPException(status_code=404, detail="Log not found")
    if body.log_type is not None: log.log_type = body.log_type; log.title = body.log_type
    if body.pain_level is not None: log.pain_level = body.pain_level
    if body.bleeding_level is not None: log.bleeding_level = body.bleeding_level
    if body.mood is not None: log.mood = body.mood
    if body.notes is not None: log.notes = body.notes
    db.commit(); db.refresh(log)
    return {"id": str(log.id), "log_type": log.log_type, "pain_level": log.pain_level,
            "bleeding_level": log.bleeding_level, "mood": log.mood, "notes": log.notes, "log_date": str(log.log_date)}

@app.delete("/health-logs/{log_id}")
def delete_health_log(log_id: str, db: Session = Depends(get_db)):
    log = db.query(HealthLog).filter(HealthLog.id == uuid.UUID(log_id)).first()
    if not log: raise HTTPException(status_code=404, detail="Log not found")
    db.delete(log); db.commit()
    return {"message": "Health log deleted"}

# ════════════════════════════════════
#             CHAT
# ════════════════════════════════════

CHAT_RESPONSES = {
    "period": "Period symptoms are common. Drink warm water, use a heating pad, and rest. If pain exceeds 8/10, consult a doctor.",
    "cramp": "Cramps can be eased with gentle yoga, warm compresses, and over-the-counter pain relief.",
    "headache": "Stay hydrated and rest in a dark room. Persistent headaches could be hormonal migraines.",
    "pregnant": "If you suspect pregnancy, take a home test and schedule a visit with your OB/GYN.",
    "mood": "Mood swings are normal during hormonal changes. Try deep breathing, exercise, or journaling.",
    "bleeding": "Track bleeding daily. Heavy bleeding for more than 7 days may need medical attention.",
    "nausea": "Ginger tea and small frequent meals can help. Persistent nausea should be evaluated.",
    "fatigue": "Ensure adequate iron intake, stay hydrated, and maintain a regular sleep schedule.",
    "pain": "Log your pain level daily. Persistent high pain should be discussed with your doctor.",
    "breast": "Breast tenderness before periods is common. Wear a supportive bra and reduce caffeine.",
    "sleep": "Try maintaining a consistent sleep schedule. Avoid screens 1 hour before bed.",
    "anxiety": "Practice mindfulness and deep breathing. Consider speaking with a counselor.",
    "weight": "Hormonal changes can affect weight. Focus on balanced nutrition and regular exercise.",
    "acne": "Hormonal acne is common. Keep skin clean and consider consulting a dermatologist.",
}

@app.post("/chat")
def chat(body: ChatRequest, authorization: str = Header(...)):
    verify_token(authorization)
    msg = body.message.lower()
    for keyword, response in CHAT_RESPONSES.items():
        if keyword in msg:
            return {"reply": response}
    return {"reply": "Thank you for sharing. I recommend logging your symptoms and discussing them with your healthcare provider for personalized advice. 💊"}

# ════════════════════════════════════
#         SYMPTOM CHECKER
# ════════════════════════════════════

SYMPTOM_DB = [
    {"keywords": ["headache", "head pain", "migraine"], "causes": ["Tension headache", "Hormonal migraine", "Dehydration", "Stress"], "severity": "Mild to Moderate", "recommendations": ["Stay hydrated", "Rest in a dark room", "Try over-the-counter pain relief", "Track headache frequency"]},
    {"keywords": ["cramp", "abdominal pain", "stomach pain"], "causes": ["Menstrual cramps", "Ovulation pain", "Digestive issues", "Endometriosis"], "severity": "Moderate", "recommendations": ["Use a heating pad", "Try gentle yoga", "Take ibuprofen if needed", "See doctor if severe"]},
    {"keywords": ["nausea", "vomit", "sick"], "causes": ["Morning sickness", "Hormonal changes", "Food sensitivity", "Gastritis"], "severity": "Mild to Moderate", "recommendations": ["Drink ginger tea", "Eat small frequent meals", "Avoid spicy foods", "Consult doctor if persistent"]},
    {"keywords": ["fatigue", "tired", "exhausted"], "causes": ["Iron deficiency", "Hormonal imbalance", "Poor sleep", "Thyroid issues"], "severity": "Mild", "recommendations": ["Eat iron-rich foods", "Get 7-9 hours sleep", "Check iron levels", "Stay active"]},
    {"keywords": ["irregular", "missed period", "late period"], "causes": ["Stress", "PCOS", "Thyroid disorder", "Early pregnancy"], "severity": "Moderate", "recommendations": ["Take a pregnancy test", "Track cycle for 3 months", "Reduce stress", "Consult gynecologist"]},
    {"keywords": ["heavy bleeding", "clot"], "causes": ["Fibroids", "Hormonal imbalance", "Endometriosis", "Polyps"], "severity": "High", "recommendations": ["Use menstrual tracking", "Check iron levels", "See gynecologist urgently", "Don't ignore > 7 days"]},
    {"keywords": ["mood swing", "anxiety", "depression", "sad"], "causes": ["PMS / PMDD", "Hormonal fluctuations", "Stress", "Depression"], "severity": "Mild to Moderate", "recommendations": ["Practice mindfulness", "Exercise regularly", "Talk to a counselor", "Track moods daily"]},
    {"keywords": ["discharge", "itching", "burning"], "causes": ["Yeast infection", "Bacterial vaginosis", "UTI", "STI"], "severity": "Moderate to High", "recommendations": ["Avoid scented products", "Wear cotton underwear", "See doctor for diagnosis", "Don't self-medicate"]},
    {"keywords": ["breast", "tender", "sore breast"], "causes": ["Hormonal changes", "Pregnancy", "Fibrocystic changes"], "severity": "Mild", "recommendations": ["Wear supportive bra", "Reduce caffeine", "Track with cycle", "See doctor if lump found"]},
    {"keywords": ["back pain", "lower back"], "causes": ["Menstrual pain", "Poor posture", "Muscle strain", "Kidney issues"], "severity": "Mild to Moderate", "recommendations": ["Apply warm compress", "Practice good posture", "Stretch regularly", "See doctor if radiating"]},
]

@app.post("/symptom-check")
def symptom_check(body: SymptomRequest, authorization: str = Header(...)):
    verify_token(authorization)
    text = body.symptoms.lower()
    causes, recs, severity = [], [], "Mild"

    for entry in SYMPTOM_DB:
        for kw in entry["keywords"]:
            if kw in text:
                causes.extend(entry["causes"])
                recs.extend(entry["recommendations"])
                if "High" in entry["severity"]: severity = "High"
                elif "Moderate" in entry["severity"] and severity != "High": severity = "Moderate"
                break

    if not causes:
        causes = ["General discomfort", "Possible stress-related symptoms"]
        recs = ["Track symptoms daily", "Stay hydrated", "Get adequate rest", "Consult a healthcare provider"]

    return {"severity": severity, "causes": list(dict.fromkeys(causes))[:6], "recommendations": list(dict.fromkeys(recs))[:6]}
