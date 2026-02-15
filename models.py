from sqlalchemy import Column, String, Integer, Text, Date, DateTime, Float, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid
from datetime import datetime, date, timedelta
from database import engine

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=True)
    age = Column(Integer)
    role = Column(String)  # "patient" or "doctor"
    phone = Column(String, nullable=True)

    health_logs = relationship("HealthLog", back_populates="user")
    pregnancy_profile = relationship("PregnancyProfile", back_populates="user", uselist=False)

class PregnancyProfile(Base):
    __tablename__ = "pregnancy_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    last_period_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    pregnancy_type = Column(String, nullable=False, default="continue")  # "continue" or "abort"
    blood_group = Column(String, nullable=True)
    weight = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    existing_conditions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="pregnancy_profile")

class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    specialization = Column(String, nullable=True)
    hospital = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    available = Column(Boolean, default=True)
    invite_code = Column(String, unique=True, nullable=True)

    user = relationship("User")

class DoctorPatientLink(Base):
    __tablename__ = "doctor_patient_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class MedicalReport(Base):
    __tablename__ = "medical_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    report_type = Column(String, nullable=False)  # "blood_test", "ultrasound", "prescription", "other"
    notes = Column(Text, nullable=True)
    file_data = Column(Text, nullable=True)  # base64 encoded file
    file_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Medication(Base):
    __tablename__ = "medications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    prescribed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    dosage = Column(String, nullable=True)
    frequency = Column(String, nullable=True)  # "1x daily", "2x daily", "3x daily"
    times = Column(JSON, nullable=True)  # ["08:00", "14:00", "20:00"]
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DietPlan(Base):
    __tablename__ = "diet_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    meal_type = Column(String, nullable=False)  # "breakfast", "lunch", "snack", "dinner"
    food_items = Column(Text, nullable=False)
    calories = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    day_of_week = Column(String, nullable=True)  # "monday", "tuesday", etc.
    created_at = Column(DateTime, default=datetime.utcnow)

class EmergencyRequest(Base):
    __tablename__ = "emergency_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    status = Column(String, default="pending")  # "pending", "accepted", "resolved"
    accepted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    consultation_type = Column(String, nullable=True)  # "online", "visit"
    created_at = Column(DateTime, default=datetime.utcnow)

class HealthLog(Base):
    __tablename__ = "health_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    log_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    log_date = Column(Date, nullable=False, default=date.today, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    pain_level = Column(Integer, nullable=True)
    bleeding_level = Column(String, nullable=True)
    mood = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    user = relationship("User", back_populates="health_logs")

Base.metadata.create_all(bind=engine, checkfirst=True)
