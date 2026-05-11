from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, text
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), server_default=text("'STUDENT'"))
    admin_id = Column(Integer, ForeignKey("users.id"))
    quota_ram = Column(Integer, server_default=text("4096"))
    quota_cpu = Column(Integer, server_default=text("4"))
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
