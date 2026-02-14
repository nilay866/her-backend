from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import get_db
from models import User, HealthLog
from jose import jwt, JWTError
import bcrypt
from pydantic import BaseModel
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
import uuid, os

load_dotenv()

app = FastAPI(title="HerCare API")

# ────── CORS ──────
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
