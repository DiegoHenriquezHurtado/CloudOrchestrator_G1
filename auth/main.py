from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import jwt

from database import get_db
from models import User
from schemas import UserCreate, UserResponse, UserLogin, Token, UserVerifyResponse
from security import get_password_hash, verify_password, create_access_token, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from datetime import timedelta

app = FastAPI(title="Orchestrator Auth API")

security = HTTPBearer()

@app.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    if user.role not in ["STUDENT", "SLICE_ADMIN", "SYSTEM_ADMIN"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    if user.role == "STUDENT" and user.admin_id is None:
        raise HTTPException(status_code=400, detail="admin_id is mandatory for STUDENT role")
    
    result = await db.execute(select(User).where(User.username == user.username))
    if result.scalars().first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    
    if user.admin_id is not None:
        admin_result = await db.execute(select(User).where(User.id == user.admin_id))
        admin = admin_result.scalars().first()
        if not admin or admin.role != "SLICE_ADMIN":
            raise HTTPException(status_code=400, detail="admin_id does not correspond to a SLICE_ADMIN")

    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        password_hash=hashed_password,
        role=user.role,
        admin_id=user.admin_id
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    return new_user

def _decode_caller(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token requerido")
    try:
        payload = jwt.decode(auth.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
        return {"id": int(payload["sub"]), "role": payload["role"]}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

@app.get("/auth/admins")
async def list_admins(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.role == "SLICE_ADMIN"))
    admins = result.scalars().all()
    return {"admins": [{"id": a.id, "username": a.username} for a in admins]}

@app.get("/auth/users")
async def list_users(request: Request, db: AsyncSession = Depends(get_db)):
    caller = _decode_caller(request)
    if caller["role"] == "SYSTEM_ADMIN":
        result = await db.execute(select(User))
    elif caller["role"] == "SLICE_ADMIN":
        result = await db.execute(select(User).where(User.admin_id == caller["id"]))
    else:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    users = result.scalars().all()
    return {"users": [{"id": u.id, "username": u.username, "role": u.role} for u in users]}

@app.post("/auth/login", response_model=Token)
async def login(user_data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == user_data.username))
    user = result.scalars().first()
    
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role},
        expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/verify", response_model=UserVerifyResponse)
async def verify(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        
    return UserVerifyResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        admin_id=user.admin_id
    )
