from pydantic import BaseModel, ConfigDict
from typing import Optional

class UserLogin(BaseModel):
    username: str
    password: str

class UserRegister(BaseModel):
    username: str
    password: str
    role: Optional[str] = "STUDENT"

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    sub: str
    username: str
    role: str
    exp: int

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    admin_id: Optional[int]
    
    model_config = ConfigDict(from_attributes=True)
