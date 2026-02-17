# ════════════════════════════════════
# Admin API Routes
# ════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
from models import User, UserRole, Role, AuditLog, Organization
from auth import get_current_user_with_roles, require_role_dep, hash_password, get_client_ip
from audit import AuditService
from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["admin"])

# ────── Schemas ──────
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    age: Optional[int] = None
    phone: Optional[str] = None
    role: str = "patient"  # "patient", "doctor", "hospital_admin"

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None

class RoleAssignRequest(BaseModel):
    user_id: str
    role_name: str

class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# ────── Dashboard ──────
@router.get("/dashboard")
def get_dashboard(
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """Get admin dashboard overview"""
    
    total_users = db.query(User).count()
    total_doctors = db.query(User).filter(User.role == "doctor").count()
    total_patients = db.query(User).filter(User.role == "patient").count()
    total_organizations = db.query(Organization).count()
    
    return {
        "total_users": total_users,
        "total_doctors": total_doctors,
        "total_patients": total_patients,
        "total_organizations": total_organizations,
        "admin_name": current_user.name,
        "admin_id": str(current_user.id)
    }

# ────── User Management ──────
@router.post("/users")
def create_user(
    body: UserCreate,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Create a new user (Admin only)"""
    
    # Check if email exists
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    new_user = User(
        id=uuid.uuid4(),
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        age=body.age,
        phone=body.phone,
        role=body.role
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Assign default role
    default_role = db.query(Role).filter(Role.name == body.role).first()
    if default_role:
        user_role = UserRole(
            id=uuid.uuid4(),
            user_id=new_user.id,
            role_id=default_role.id,
            assigned_by=current_user.id
        )
        db.add(user_role)
        db.commit()
    
    # Audit log
    ip = get_client_ip(request) if request else None
    AuditService.log_user_creation(
        db=db,
        admin_id=str(current_user.id),
        new_user_id=str(new_user.id),
        user_data={"name": body.name, "email": body.email, "role": body.role},
        ip_address=ip
    )
    
    return {
        "id": str(new_user.id),
        "name": new_user.name,
        "email": new_user.email,
        "role": new_user.role,
        "message": "User created successfully"
    }

@router.get("/users")
def list_users(
    skip: int = 0,
    limit: int = 50,
    role_filter: Optional[str] = None,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """List all users (Admin only)"""
    
    query = db.query(User)
    
    if role_filter:
        query = query.filter(User.role == role_filter)
    
    users = query.offset(skip).limit(limit).all()
    
    return {
        "total": db.query(User).count(),
        "users": [
            {
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "role": u.role,
                "age": u.age,
                "phone": u.phone
            }
            for u in users
        ]
    }

@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """Get user details (Admin only)"""
    
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user roles
    user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
    roles = [db.query(Role).filter(Role.id == ur.role_id).first().name for ur in user_roles]
    
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "age": user.age,
        "phone": user.phone,
        "roles": roles
    }

@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Update user (Admin only)"""
    
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    old_data = {
        "name": user.name,
        "email": user.email,
        "age": user.age,
        "phone": user.phone
    }
    
    if body.name:
        user.name = body.name
    if body.email:
        # Check if email already taken
        if db.query(User).filter(User.email == body.email, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="Email already taken")
        user.email = body.email
    if body.age:
        user.age = body.age
    if body.phone:
        user.phone = body.phone
    
    db.commit()
    
    # Audit log
    ip = get_client_ip(request) if request else None
    AuditService.log_user_update(
        db=db,
        admin_id=str(current_user.id),
        user_id=user_id,
        old_data=old_data,
        new_data={"name": user.name, "email": user.email, "age": user.age, "phone": user.phone},
        ip_address=ip
    )
    
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "message": "User updated successfully"
    }

@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current_user: User = Depends(require_role_dep("super_admin")),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Delete user (Super Admin only)"""
    
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_data = {
        "name": user.name,
        "email": user.email,
        "role": user.role
    }
    
    # Delete user roles
    db.query(UserRole).filter(UserRole.user_id == user.id).delete()
    
    # Delete user
    db.delete(user)
    db.commit()
    
    # Audit log
    ip = get_client_ip(request) if request else None
    AuditService.log_user_deletion(
        db=db,
        admin_id=str(current_user.id),
        user_id=user_id,
        user_data=user_data,
        ip_address=ip
    )
    
    return {"message": "User deleted successfully"}

# ────── Role Management ──────
@router.post("/users/{user_id}/roles")
def assign_role(
    user_id: str,
    body: RoleAssignRequest,
    current_user: User = Depends(require_role_dep("super_admin")),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Assign role to user (Super Admin only)"""
    
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = db.query(Role).filter(Role.name == body.role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Check if user already has role
    existing = db.query(UserRole).filter(
        UserRole.user_id == user.id,
        UserRole.role_id == role.id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="User already has this role")
    
    # Assign role
    user_role = UserRole(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=role.id,
        assigned_by=current_user.id
    )
    
    db.add(user_role)
    db.commit()
    
    # Audit log
    ip = get_client_ip(request) if request else None
    AuditService.log_role_assignment(
        db=db,
        admin_id=str(current_user.id),
        user_id=user_id,
        role_name=body.role_name,
        ip_address=ip
    )
    
    return {
        "user_id": user_id,
        "role_name": body.role_name,
        "message": "Role assigned successfully"
    }

@router.get("/users/{user_id}/roles")
def get_user_roles(
    user_id: str,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """Get all roles assigned to a user"""
    
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
    
    roles = []
    for ur in user_roles:
        role = db.query(Role).filter(Role.id == ur.role_id).first()
        if role:
            roles.append({
                "name": role.name,
                "description": role.description,
                "assigned_at": ur.assigned_at
            })
    
    return {"user_id": user_id, "roles": roles}

# ────── Audit Logs ──────
@router.get("/audit-logs")
def get_audit_logs(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """Get audit logs (Admin only)"""
    
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "total": db.query(AuditLog).count(),
        "logs": [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": str(log.resource_id) if log.resource_id else None,
                "status": log.status,
                "created_at": log.created_at.isoformat(),
                "details": log.details
            }
            for log in logs
        ]
    }

@router.get("/audit-logs/user/{user_id}")
def get_user_audit_logs(
    user_id: str,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """Get audit logs for a specific user"""
    
    logs = db.query(AuditLog).filter(
        AuditLog.user_id == uuid.UUID(user_id)
    ).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "user_id": user_id,
        "logs": [
            {
                "id": str(log.id),
                "action": log.action,
                "resource_type": log.resource_type,
                "status": log.status,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }

# ────── Doctor Approval ──────
@router.get("/doctors/pending-approval")
def get_pending_doctors(
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """Get doctors pending approval"""
    
    doctors = db.query(User).filter(User.role == "doctor").all()
    
    pending = [
        {
            "id": str(d.id),
            "name": d.name,
            "email": d.email,
            "phone": d.phone
        }
        for d in doctors
    ]
    
    return {"pending_doctors": pending}

@router.post("/doctors/{doctor_id}/approve")
def approve_doctor(
    doctor_id: str,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Approve a doctor"""
    
    doctor = db.query(User).filter(User.id == uuid.UUID(doctor_id)).first()
    if not doctor or doctor.role != "doctor":
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    # Audit log
    ip = get_client_ip(request) if request else None
    AuditService.log(
        db=db,
        user_id=str(current_user.id),
        action="approve_doctor",
        resource_type="user",
        resource_id=doctor_id,
        ip_address=ip,
        details=f"Approved doctor {doctor.name}"
    )
    
    return {
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "message": "Doctor approved successfully"
    }

# ────── Organizations ──────
@router.get("/organizations")
def list_organizations(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(require_role_dep("super_admin", "hospital_admin")),
    db: Session = Depends(get_db)
):
    """List organizations"""
    
    orgs = db.query(Organization).offset(skip).limit(limit).all()
    
    return {
        "total": db.query(Organization).count(),
        "organizations": [
            {
                "id": str(org.id),
                "name": org.name,
                "type": org.type,
                "email": org.email,
                "is_verified": org.is_verified
            }
            for org in orgs
        ]
    }

@router.post("/organizations/{org_id}/verify")
def verify_organization(
    org_id: str,
    current_user: User = Depends(require_role_dep("super_admin")),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Verify an organization"""
    
    org = db.query(Organization).filter(Organization.id == uuid.UUID(org_id)).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    org.is_verified = True
    db.commit()
    
    # Audit log
    ip = get_client_ip(request) if request else None
    AuditService.log(
        db=db,
        user_id=str(current_user.id),
        action="verify_organization",
        resource_type="organization",
        resource_id=org_id,
        ip_address=ip,
        details=f"Verified organization {org.name}"
    )
    
    return {
        "org_id": org_id,
        "org_name": org.name,
        "message": "Organization verified successfully"
    }
