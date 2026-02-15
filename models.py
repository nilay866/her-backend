from sqlalchemy import Column, String, Integer, Text, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid
from datetime import datetime, date
from database import engine

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=True)
    age = Column(Integer)
    role = Column(String)

    health_logs = relationship("HealthLog", back_populates="user")

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
