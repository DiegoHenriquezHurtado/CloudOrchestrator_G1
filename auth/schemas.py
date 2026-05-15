from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    admin_id: Optional[int] = None

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    admin_id: Optional[int] = None
    quota_ram: int
    quota_cpu: int

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    sub: int
    username: str
    role: str
    exp: int

class UserVerifyResponse(BaseModel):
    id: int
    username: str
    role: str
    admin_id: Optional[int] = None
