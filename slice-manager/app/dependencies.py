import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import User

security = HTTPBearer()
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey_change_in_production")
ALGORITHM = "HS256"

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def get_current_student(user: User = Depends(get_current_user)):
    if user.role != "STUDENT":
        raise HTTPException(status_code=403, detail="Not enough permissions. STUDENT role required.")
    return user

async def get_current_slice_admin(user: User = Depends(get_current_user)):
    if user.role not in ["SLICE_ADMIN", "SYSTEM_ADMIN"]:
        raise HTTPException(status_code=403, detail="Not enough permissions. SLICE_ADMIN role required.")
    return user
