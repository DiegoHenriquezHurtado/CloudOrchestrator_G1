from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
import models, schemas, utils
from database import get_db, engine

app = FastAPI(title="Orquestador Cloud - Auth Service")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

async def get_current_user_token(token: str = Depends(oauth2_scheme)):
    if not token:
        return None
    payload = utils.decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload

@app.post("/auth/login", response_model=schemas.Token)
async def login(user_credentials: schemas.UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.User).where(models.User.username == user_credentials.username))
    user = result.scalars().first()

    if not user or not utils.verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = utils.create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/register", response_model=schemas.UserResponse)
async def register(user_data: schemas.UserRegister, token: Optional[str] = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    admin_id = None
    role_to_assign = user_data.role or "STUDENT"

    if token:
        payload = await get_current_user_token(token)
        if payload:
            creator_role = payload.get("role")
            if creator_role == "SLICE_ADMIN":
                admin_id = int(payload.get("sub"))
                role_to_assign = "STUDENT"
            elif creator_role == "STUDENT":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Students cannot register new users")
            # If SYSTEM_ADMIN, they can register anyone without admin_id constraints, unless specified

    # Check if user exists
    result = await db.execute(select(models.User).where(models.User.username == user_data.username))
    if result.scalars().first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    new_user = models.User(
        username=user_data.username,
        password_hash=utils.get_password_hash(user_data.password),
        role=role_to_assign,
        admin_id=admin_id
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@app.get("/auth/verify", response_model=schemas.TokenData)
async def verify(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = await get_current_user_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return schemas.TokenData(**payload)
