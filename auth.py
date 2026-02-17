from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
import os
import uuid

# ─── Config ───
SECRET_KEY = os.getenv("SECRET_KEY", "hercare-super-secret-key-change-me")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# ─── Password Hashing (using bcrypt directly) ───
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# ─── JWT Token with Roles ───
def create_token(data: dict, expires_delta: timedelta = None) -> str:
    """Create JWT token with roles"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_token_with_roles(user_id: str, user_name: str, roles: list = None) -> str:
    """Create JWT token with user roles embedded"""
    data = {
        "sub": user_id,
        "user_id": user_id,
        "name": user_name,
        "roles": roles or []
    }
    return create_token(data)

# ─── Get Current User (dependency) ───
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Get current authenticated user from token"""
    from models import User

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if user is None:
        raise credentials_exception

    return user

def get_current_user_with_roles(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Get current user with their roles"""
    from models import User, UserRole, Role

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if user is None:
        raise credentials_exception

    # Get user roles
    user_roles = db.query(UserRole).filter(UserRole.user_id == uuid.UUID(user_id)).all()
    roles = []
    permissions = {}
    
    for user_role in user_roles:
        role = db.query(Role).filter(Role.id == user_role.role_id).first()
        if role:
            roles.append(role.name)
            permissions.update(role.permissions)

    # Backward compatibility for users that only have users.role set
    # but no entry in user_roles yet.
    if user.role and user.role not in roles:
        roles.append(user.role)
    
    # Attach roles and permissions to user object
    user.roles = roles
    user.permissions = permissions
    
    return user

def require_role_dep(*required_roles):
    """FastAPI dependency-style role check."""
    def dependency(current_user = Depends(get_current_user_with_roles)):
        current_roles = set(getattr(current_user, "roles", []) or [])
        if current_user and getattr(current_user, "role", None):
            current_roles.add(current_user.role)

        if not any(role in current_roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(required_roles)}"
            )
        return current_user
    return dependency

# ─── Helper: Check if user has role ───
def has_role(user, required_role: str) -> bool:
    """Check if user has a specific role"""
    if not hasattr(user, 'roles'):
        return False
    return required_role in user.roles

# ─── Helper: Check if user has permission ───
def has_permission(user, required_permission: str) -> bool:
    """Check if user has a specific permission"""
    if not hasattr(user, 'permissions'):
        return False
    return user.permissions.get(required_permission, False)

from functools import wraps

# ─── Require Role Decorator ───
def require_role(*required_roles):
    """Decorator to require specific role(s)"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Look for current_user in kwargs (injected by Depends)
            # Use get_current_user_with_roles as a source of truth
            db = kwargs.get("db")
            token = kwargs.get("authorization") # Some routes might have this
            
            # If user is already in kwargs, use it
            user = kwargs.get("current_user")
            
            # If user doesn't have roles loaded, load them
            if user and (not hasattr(user, "roles") or not user.roles):
                # We need DB to load roles. If db not in kwargs, we can't do much here 
                # but most endpoints have db: Session = Depends(get_db)
                if db:
                    from models import UserRole, Role
                    user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
                    user.roles = [db.query(Role).filter(Role.id == ur.role_id).first().name for ur in user_roles]
                    user.permissions = {}
                    for ur in user_roles:
                        r = db.query(Role).filter(Role.id == ur.role_id).first()
                        if r: user.permissions.update(r.permissions)

            if not user or not any(role in getattr(user, "roles", []) for role in required_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required roles: {', '.join(required_roles)}"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# ─── Require Permission Decorator ───
def require_permission(*required_permissions):
    """Decorator to require specific permission(s)"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("current_user")
            # Ensure roles/permissions are loaded
            if user and (not hasattr(user, "permissions") or not user.permissions):
                db = kwargs.get("db")
                if db:
                    from models import UserRole, Role
                    user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
                    user.permissions = {}
                    user.roles = []
                    for ur in user_roles:
                        r = db.query(Role).filter(Role.id == ur.role_id).first()
                        if r:
                            user.roles.append(r.name)
                            user.permissions.update(r.permissions)

            if not user or not any(getattr(user, "permissions", {}).get(perm, False) for perm in required_permissions):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required permissions: {', '.join(required_permissions)}"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# ─── Get IP Address ───
def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    if request.headers.get('x-forwarded-for'):
        return request.headers.get('x-forwarded-for').split(',')[0].strip()
    return request.client.host if request.client else "unknown"
