from typing import Optional
from pydantic import BaseModel, EmailStr
from app.models.user import UserRole, UserStatus

class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str
    phone: Optional[str] = None
    full_name: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    user_id: str
    username: str

class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: UserRole
    status: UserStatus
    phone: Optional[str] = None
    full_name: Optional[str] = None
    is_kyc_verified: bool

    class Config:
        from_attributes = True

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class MerchantApplicationRequest(BaseModel):
    business_name: str
    trade_license: Optional[str] = None
    contact_phone: str
    website: Optional[str] = None
