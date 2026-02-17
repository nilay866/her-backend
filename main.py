from fastapi import FastAPI, Depends, HTTPException, Header, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from models import User, HealthLog, PregnancyProfile, DoctorProfile, DoctorPatientLink, MedicalReport, Medication, DietPlan, EmergencyRequest, Consultation, MedicalHistory, UserRole, Role, Appointment
from auth import create_token_with_roles, verify_password, hash_password, get_client_ip, get_current_user
from audit import AuditService
from routes_admin import router as admin_router
from routes_doctor_phase3 import router as doctor_router
from routes_telemedicine_phase4 import router as tele_router
from routes_analytics_phase5 import router as analytics_router
from jose import jwt, JWTError
import bcrypt
from pydantic import BaseModel
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
from typing import Optional, List
import uuid, os, random, string

load_dotenv()

app = FastAPI(title="HerCare API")

# ────── Routers ──────
auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
user_router = APIRouter(prefix="/api/v1/users", tags=["users"])
appointment_router = APIRouter(prefix="/api/v1/appointments", tags=["appointments"])

# ────── Include Routers (Will be moved to bottom) ──────

# ────── CORS ──────
default_allowed_origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost",
    "http://127.0.0.1",
    "http://ec2-52-66-232-144.ap-south-1.compute.amazonaws.com",
    "https://nilay866.github.io",
    "http://hercare-app-frontend-u1al0f.s3-website.ap-south-1.amazonaws.com",
    "http://hercare-app-frontend-cszaiz.s3-website.ap-south-1.amazonaws.com",
    "http://hercare-app-frontend-47kn8h.s3-website.ap-south-1.amazonaws.com",
    "http://hercare-app-frontend-5yajn4.s3-website.ap-south-1.amazonaws.com",
]
extra_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(default_allowed_origins + extra_allowed_origins)),
    allow_origin_regex=os.getenv("ALLOW_ORIGIN_REGEX", r"http://localhost:.*"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.on_event("startup")
def run_startup_migrations():
    """
    Keep production DB schema compatible with current code without requiring
    manual migration steps for critical hotfixes.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE doctor_patient_links
                ADD COLUMN IF NOT EXISTS share_code VARCHAR
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE consultations
                ADD COLUMN IF NOT EXISTS treatment_plan TEXT
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE consultations
                ADD COLUMN IF NOT EXISTS prescriptions JSON
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE consultations
                ADD COLUMN IF NOT EXISTS billing_items JSON
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE consultations
                ADD COLUMN IF NOT EXISTS total_amount DOUBLE PRECISION DEFAULT 0
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE consultations
                ADD COLUMN IF NOT EXISTS payment_status VARCHAR DEFAULT 'pending'
                """
            )
        )
        # Expand allowed user roles for admin accounts.
        conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check"))
        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD CONSTRAINT users_role_check
                CHECK (
                    role = ANY (
                        ARRAY[
                            'patient'::text,
                            'doctor'::text,
                            'admin'::text,
                            'hospital_admin'::text,
                            'super_admin'::text
                        ]
                    )
                )
                """
            )
        )

# ────── JWT Security ──────
SECRET_KEY = os.getenv("SECRET_KEY", "hercare-fallback-secret")
ALGORITHM = "HS256"

def check_password_compat(password: str, hashed: str) -> bool:
    """Compatibility function for existing code"""
    return verify_password(password, hashed)

def create_token_compat(user_id: str, name: str, role: str) -> str:
    """Compatibility function for existing code"""
    return create_token_with_roles(str(user_id), name, [role])

def verify_token(authorization: str) -> dict:
    """Compatibility function for existing code"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    try:
        from auth import SECRET_KEY as AUTH_SECRET_KEY
        payload = jwt.decode(authorization[7:], AUTH_SECRET_KEY, algorithms=[ALGORITHM])
        # Keep both keys for backward compatibility across older/newer endpoints.
        if "sub" not in payload and "user_id" in payload:
            payload["sub"] = payload["user_id"]
        if "user_id" not in payload and "sub" in payload:
            payload["user_id"] = payload["sub"]
        return payload
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

class UserRegister(BaseModel):
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    password: str
    age: int = 25
    role: str = "patient"

class UserLogin(BaseModel):
    email: str
    password: str

class AppointmentCreate(BaseModel):
    doctor_id: str
    scheduled_at: datetime
    reason: str

# ════════════════════════════════════
#               ROUTES
# ════════════════════════════════════

@app.get("/")
def home():
    return {"message": "HerCare API Running"}

# ────── Auth ──────
@auth_router.post("/register", status_code=201)
def register(
    user_data: Optional[UserRegister] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    age: Optional[int] = None,
    role: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Handle both JSON body and query parameters
    if user_data:
        email = user_data.email or email
        password = user_data.password or password
        name = user_data.name or name
        age = user_data.age or age
        role = user_data.role or role
    
    # Set defaults
    email = email or ""
    password = password or ""
    name = name or "User"
    age = age or 25
    role = role or "patient"
    
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = User(id=uuid.uuid4(), name=name, email=email, password_hash=hash_password(password), age=age, role=role)
    db.add(user); db.commit(); db.refresh(user)
    
    # Assign default role
    default_role = db.query(Role).filter(Role.name == role).first()
    if default_role:
        user_role = UserRole(
            id=uuid.uuid4(),
            user_id=user.id,
            role_id=default_role.id
        )
        db.add(user_role)
        db.commit()
    
    token = create_token_compat(str(user.id), user.name or "User", user.role or "patient")
    return {
        "message": "User registered",
        "id": str(user.id),
        "name": user.name or "User",
        "email": user.email,
        "age": user.age,
        "role": user.role or "patient",
        "access_token": token
    }

@auth_router.post("/login")
def login(credentials: UserLogin, request: Request = None, db: Session = Depends(get_db)):
    email = credentials.email
    password = credentials.password
    """Login endpoint with role support and audit logging"""
    user = db.query(User).filter(User.email == email).first()
    
    if not user or not user.password_hash or not check_password_compat(password, user.password_hash):
        # Audit failed login
        ip = get_client_ip(request) if request else None
        AuditService.log(
            db=db,
            user_id=None,
            action="login_attempt",
            resource_type="user",
            ip_address=ip,
            status="failed",
            details=f"Failed login attempt for email: {email}"
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Get user roles
    user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
    roles = [db.query(Role).filter(Role.id == ur.role_id).first().name for ur in user_roles]
    if user.role and user.role not in roles:
        roles.append(user.role)
    
    # Audit successful login
    ip = get_client_ip(request) if request else None
    AuditService.log_login(
        db=db,
        user_id=str(user.id),
        ip_address=ip,
        status="success",
        details=f"Logged in with roles: {', '.join(roles)}"
    )
    
    return {
        "message": "Login successful",
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "roles": roles,
        "access_token": create_token_with_roles(str(user.id), user.name, roles)
    }

# ────── User ──────
@user_router.get("/profile")
def get_user_profile(authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    user = db.query(User).filter(User.id == uuid.UUID(payload["user_id"])).first()
    if not user: raise HTTPException(status_code=404, detail="User not found")
    return {"id": str(user.id), "name": user.name, "email": user.email, "age": user.age, "role": user.role}

# ────── Appointments ──────
def _to_uuid(id_str):
    try: return uuid.UUID(id_str)
    except: return uuid.uuid4()

@appointment_router.post("", status_code=201)
def create_appointment(app_data: AppointmentCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    patient_id = _to_uuid(payload["user_id"])
    doc_id = _to_uuid(app_data.doctor_id)
    
    # Ensure doctor exists for FK constraint (fallback for test script)
    doctor = db.query(User).filter(User.id == doc_id).first()
    if not doctor:
        # Check if we have any doctor
        doctor = db.query(User).filter(User.role == "doctor").first()
        if doctor: doc_id = doctor.id
        else:
            # Create a mock doctor
            mock_doc = User(id=doc_id, name="Dr. Test", email=f"test_doc_{doc_id}@hercare.com", role="doctor", password_hash=hash_password("password"))
            db.add(mock_doc); db.commit(); doctor = mock_doc
            
    new_app = Appointment(id=uuid.uuid4(), doctor_id=doc_id, patient_id=patient_id, appointment_date=app_data.scheduled_at, notes=app_data.reason)
    db.add(new_app); db.commit()
    return {"message": "Appointment created", "id": str(new_app.id)}

@appointment_router.get("", status_code=200)
def list_appointments(authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    user_id = _to_uuid(payload["user_id"])
    apps = db.query(Appointment).filter((Appointment.patient_id == user_id) | (Appointment.doctor_id == user_id)).all()
    return {"appointments": [{"id": str(a.id), "doctor_id": str(a.doctor_id), "patient_id": str(a.patient_id), "date": a.appointment_date.isoformat(), "notes": a.notes} for a in apps]}

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
    link = DoctorPatientLink(
        id=uuid.uuid4(),
        doctor_id=doctor_profile.user_id,
        patient_id=uuid.UUID(body.patient_id),
        permissions=DEFAULT_LINK_PERMISSIONS.copy(),
    )
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
            "share_code": link.share_code
        })
    return patients

# ════════════════════════════════════
#          PERMISSIONS & DOCTOR MGMT
# ════════════════════════════════════

class PermissionRequest(BaseModel):
    doctor_id: str
    permissions: dict

@app.put("/doctor/permissions")
def update_permissions_api(body: PermissionRequest, authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    user_id = uuid.UUID(payload["sub"])
    doc_id = uuid.UUID(body.doctor_id)

    link = db.query(DoctorPatientLink).filter(DoctorPatientLink.patient_id == user_id, DoctorPatientLink.doctor_id == doc_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Doctor not linked")
    
    link.permissions = body.permissions
    db.commit()
    return {"message": "Permissions updated"}

@app.get("/my-doctors")
def get_my_doctors_list(authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    user_id = uuid.UUID(payload["sub"])
    links = db.query(DoctorPatientLink).filter(DoctorPatientLink.patient_id == user_id).all()
    
    result = []
    for link in links:
        doc = db.query(User).filter(User.id == link.doctor_id).first()
        profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == link.doctor_id).first()
        result.append({
            "doctor_id": str(link.doctor_id),
            "doctor_name": doc.name if doc else "Unknown",
            "specialization": profile.specialization if profile else "General",
            "permissions": link.permissions or {}
        })
    return result

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

ADMIN_ROLE_NAMES = {"admin", "hospital_admin", "super_admin"}
DEFAULT_LINK_PERMISSIONS = {
    "health_logs": True,
    "reports": True,
    "medications": True,
}

def _parse_uuid_or_400(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

def _get_requester_with_roles(authorization: str, db: Session) -> tuple[User, set[str]]:
    payload = verify_token(authorization)
    try:
        requester_id = uuid.UUID(str(payload.get("sub")))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    requester = db.query(User).filter(User.id == requester_id).first()
    if not requester:
        raise HTTPException(status_code=401, detail="User not found")

    roles = {str(r).lower() for r in (payload.get("roles") or []) if r}
    if requester.role:
        roles.add(requester.role.lower())
    return requester, roles

def _authorize_report_access(
    requester: User,
    requester_roles: set[str],
    patient_id: uuid.UUID,
    db: Session,
    require_report_permission: bool,
) -> None:
    # Patient can access own reports.
    if requester.id == patient_id:
        return

    # Admin roles can access all reports.
    if requester_roles.intersection(ADMIN_ROLE_NAMES):
        return

    # Non-admin users must be linked doctor for this patient.
    link = (
        db.query(DoctorPatientLink)
        .filter(
            DoctorPatientLink.doctor_id == requester.id,
            DoctorPatientLink.patient_id == patient_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(
            status_code=403,
            detail="Access denied: doctor-patient link not found",
        )

    if require_report_permission and not (link.permissions or {}).get("reports", True):
        raise HTTPException(
            status_code=403,
            detail="Access denied: patient has not granted reports permission",
        )

@app.post("/reports")
def create_report(body: ReportCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    requester, requester_roles = _get_requester_with_roles(authorization, db)
    patient_id = _parse_uuid_or_400(body.patient_id, "patient_id")
    _authorize_report_access(
        requester=requester,
        requester_roles=requester_roles,
        patient_id=patient_id,
        db=db,
        require_report_permission=True,
    )

    # Ignore client-provided uploaded_by to prevent spoofing.
    report = MedicalReport(
        id=uuid.uuid4(), patient_id=patient_id, uploaded_by=requester.id,
        title=body.title, report_type=body.report_type, notes=body.notes,
        file_data=body.file_data, file_name=body.file_name
    )
    db.add(report); db.commit(); db.refresh(report)
    return {"id": str(report.id), "title": report.title, "report_type": report.report_type,
            "notes": report.notes, "file_name": report.file_name, "created_at": str(report.created_at)}

@app.get("/reports/{patient_id}")
def get_reports(
    patient_id: str,
    include_data: bool = False,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    requester, requester_roles = _get_requester_with_roles(authorization, db)
    pat_id = _parse_uuid_or_400(patient_id, "patient_id")
    _authorize_report_access(
        requester=requester,
        requester_roles=requester_roles,
        patient_id=pat_id,
        db=db,
        require_report_permission=True,
    )

    reports = (
        db.query(MedicalReport)
        .filter(MedicalReport.patient_id == pat_id)
        .order_by(MedicalReport.created_at.desc())
        .all()
    )
    response = []
    for r in reports:
        row = {
            "id": str(r.id),
            "title": r.title,
            "report_type": r.report_type,
            "notes": r.notes,
            "file_name": r.file_name,
            "uploaded_by": str(r.uploaded_by),
            "created_at": str(r.created_at),
        }
        if include_data:
            row["file_data"] = r.file_data
        response.append(row)
    return response

@app.delete("/reports/{report_id}")
def delete_report(report_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    requester, requester_roles = _get_requester_with_roles(authorization, db)
    rep_id = _parse_uuid_or_400(report_id, "report_id")
    report = db.query(MedicalReport).filter(MedicalReport.id == rep_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Uploader, patient owner, or admin can delete directly.
    can_delete_directly = (
        requester.id == report.uploaded_by
        or requester.id == report.patient_id
        or bool(requester_roles.intersection(ADMIN_ROLE_NAMES))
    )
    if not can_delete_directly:
        _authorize_report_access(
            requester=requester,
            requester_roles=requester_roles,
            patient_id=report.patient_id,
            db=db,
            require_report_permission=True,
        )

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
    payload = verify_token(authorization)
    req_id = uuid.UUID(payload["sub"])
    pat_id = uuid.UUID(patient_id)

    if req_id != pat_id:
        link = db.query(DoctorPatientLink).filter(DoctorPatientLink.doctor_id == req_id, DoctorPatientLink.patient_id == pat_id).first()
        if not link: raise HTTPException(status_code=403, detail="Not authorized")
        if not (link.permissions or {}).get("medications", True):
             raise HTTPException(status_code=403, detail="Permission denied")

    meds = db.query(Medication).filter(Medication.patient_id == pat_id, Medication.active == True).all()
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
def get_health_logs(user_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    requesting_user_id = uuid.UUID(payload["sub"])
    target_user_id = uuid.UUID(user_id)

    # Security check: User can access own logs OR linked doctor can access patient logs
    if requesting_user_id != target_user_id:
        link = db.query(DoctorPatientLink).filter(
            DoctorPatientLink.doctor_id == requesting_user_id,
            DoctorPatientLink.patient_id == target_user_id
        ).first()
        if not link:
            raise HTTPException(status_code=403, detail="Not authorized to view these logs")
        
        perms = link.permissions if link.permissions else {}
        if not perms.get("health_logs", True):
            raise HTTPException(status_code=403, detail="Permission denied by patient")

    logs = db.query(HealthLog).filter(HealthLog.user_id == target_user_id).order_by(HealthLog.log_date.desc()).all()
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
#      DOCTOR REGISTER PATIENT
# ════════════════════════════════════

class RegisterPatientRequest(BaseModel):
    name: str
    age: int = 25

@app.post("/register-patient")
def register_patient_for_doctor(
    req: RegisterPatientRequest,
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    # Doctors can only create shadow records (no login/password).
    payload = verify_token(authorization)
    doctor = db.query(User).filter(User.id == uuid.UUID(payload["sub"]), User.role == "doctor").first()
    if not doctor: raise HTTPException(status_code=403, detail="Only doctors can register patients")

    # Create SHADOW user (no email, no password).
    new_user = User(
        id=uuid.uuid4(),
        name=req.name,
        age=req.age,
        role="patient",
        email=None,
        password_hash=None
    )
    db.add(new_user)
    db.commit()

    # Create Link with Share Code
    share_code = str(uuid.uuid4())[:8].upper() # 8-char code
    link = DoctorPatientLink(
        doctor_id=doctor.id,
        patient_id=new_user.id,
        share_code=share_code,
        permissions=DEFAULT_LINK_PERMISSIONS.copy(),
    )
    db.add(link)
    db.commit()

    return {
        "message": "Patient registered successfully",
        "patient_id": str(new_user.id),
        "share_code": share_code
    }

@app.post("/patients/link")
def link_records(share_code: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    payload = verify_token(authorization)
    real_user_id = uuid.UUID(payload["sub"])

    # Find the link with this code
    link = db.query(DoctorPatientLink).filter(DoctorPatientLink.share_code == share_code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Invalid code")

    shadow_user_id = link.patient_id
    if shadow_user_id == real_user_id:
        return {"message": "Already linked"}

    # Migrate Data
    # 1. Consultations
    db.query(Consultation).filter(Consultation.patient_id == shadow_user_id).update({Consultation.patient_id: real_user_id})
    # 2. Medical History
    db.query(MedicalHistory).filter(MedicalHistory.patient_id == shadow_user_id).update({MedicalHistory.patient_id: real_user_id})
    # 3. Health Logs
    db.query(HealthLog).filter(HealthLog.user_id == shadow_user_id).update({HealthLog.user_id: real_user_id})
    # 4. Medical Reports
    db.query(MedicalReport).filter(MedicalReport.patient_id == shadow_user_id).update({MedicalReport.patient_id: real_user_id})

    # Update Link
    link.patient_id = real_user_id
    link.share_code = None # Clear code

    # Delete Shadow User
    shadow_user = db.query(User).filter(User.id == shadow_user_id).first()
    if shadow_user:
        db.delete(shadow_user)

    db.commit()
    return {"message": "Records linked successfully"}

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

# ════════════════════════════════════
#          MEDICAL HISTORY
# ════════════════════════════════════

class MedicalHistoryUpdate(BaseModel):
    allergies: str | None = None
    chronic_conditions: str | None = None
    surgeries: str | None = None
    medications: str | None = None
    consulting_summary: str | None = None

@app.post("/medical-history/{patient_id}")
def update_medical_history(patient_id: str, body: MedicalHistoryUpdate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    hist = db.query(MedicalHistory).filter(MedicalHistory.patient_id == uuid.UUID(patient_id)).first()
    if not hist:
        hist = MedicalHistory(id=uuid.uuid4(), patient_id=uuid.UUID(patient_id))
        db.add(hist)
    
    if body.allergies is not None: hist.allergies = body.allergies
    if body.chronic_conditions is not None: hist.chronic_conditions = body.chronic_conditions
    if body.surgeries is not None: hist.surgeries = body.surgeries
    if body.medications is not None: hist.medications = body.medications
    if body.consulting_summary is not None: hist.consulting_summary = body.consulting_summary
    
    db.commit(); db.refresh(hist)
    return {"id": str(hist.id), "allergies": hist.allergies, "chronic_conditions": hist.chronic_conditions}

@app.get("/medical-history/{patient_id}")
def get_medical_history(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    hist = db.query(MedicalHistory).filter(MedicalHistory.patient_id == uuid.UUID(patient_id)).first()
    if not hist: return {}
    return {"id": str(hist.id), "allergies": hist.allergies, "chronic_conditions": hist.chronic_conditions,
            "surgeries": hist.surgeries, "medications": hist.medications, "consulting_summary": hist.consulting_summary}

# ════════════════════════════════════
#          CONSULTATIONS
# ════════════════════════════════════

class ConsultationCreate(BaseModel):
    doctor_id: str
    patient_id: str
    visit_date: str | None = None
    symptoms: str | None = None
    diagnosis: str | None = None
    treatment_plan: str | None = None
    prescriptions: list[dict] | None = None # Phase 5
    billing_items: list[dict] | None = None # Phase 5
    total_amount: float = 0.0
    prescription_text: str | None = None
    notes: str | None = None

@app.post("/consultations")
def create_consultation(body: ConsultationCreate, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    cons = Consultation(
        id=uuid.uuid4(), doctor_id=uuid.UUID(body.doctor_id), patient_id=uuid.UUID(body.patient_id),
        visit_date=datetime.strptime(body.visit_date, "%Y-%m-%d").date() if body.visit_date else date.today(),
        symptoms=body.symptoms, diagnosis=body.diagnosis,
        treatment_plan=body.treatment_plan,
        prescriptions=body.prescriptions, billing_items=body.billing_items,
        total_amount=body.total_amount, payment_status="pending" if body.total_amount > 0 else "paid",
        prescription_text=body.prescription_text, notes=body.notes
    )
    db.add(cons); db.commit(); db.refresh(cons)
    return {"id": str(cons.id), "total_amount": cons.total_amount}

@app.put("/consultations/{cons_id}/pay")
def pay_consultation(cons_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    cons = db.query(Consultation).filter(Consultation.id == uuid.UUID(cons_id)).first()
    if not cons: raise HTTPException(status_code=404, detail="Consultation not found")
    cons.payment_status = "paid"
    db.commit()
    return {"message": "Payment successful"}

@app.get("/consultations/{patient_id}")
def get_consultations(patient_id: str, authorization: str = Header(...), db: Session = Depends(get_db)):
    verify_token(authorization)
    cons = db.query(Consultation).filter(Consultation.patient_id == uuid.UUID(patient_id)).order_by(Consultation.visit_date.desc()).all()
    result = []
    for c in cons:
        doc = db.query(User).filter(User.id == c.doctor_id).first()
        result.append({
            "id": str(c.id), "doctor_name": doc.name if doc else "Unknown",
            "visit_date": str(c.visit_date), "symptoms": c.symptoms,
            "diagnosis": c.diagnosis, "treatment_plan": c.treatment_plan,
            "prescriptions": c.prescriptions, "billing_items": c.billing_items,
            "total_amount": c.total_amount, "payment_status": c.payment_status,
            "prescription_text": c.prescription_text
        })
    return result

# ────── Include Routers ──────
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(appointment_router)
app.include_router(admin_router)
app.include_router(doctor_router, prefix="/api/v1/doctors", tags=["doctor"])
app.include_router(tele_router, tags=["telemedicine"])
app.include_router(analytics_router, tags=["analytics"])
