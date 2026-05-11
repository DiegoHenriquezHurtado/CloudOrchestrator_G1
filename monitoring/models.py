from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from database import Base

class Worker(Base):
    __tablename__ = "workers"
    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(50), nullable=False)
    ip_management = Column(String(15), nullable=False)
    total_ram = Column(Integer, nullable=False)
    total_cpu = Column(Integer, nullable=False)
    current_cpu_load = Column(Float, default=0.0)
    current_ram_available = Column(Integer, default=0)
    status = Column(String(20), default="ALIVE")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    vms = relationship("VirtualMachine", back_populates="worker")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="STUDENT")
    admin_id = Column(Integer, ForeignKey("users.id"))
    slices = relationship("Slice", back_populates="user")

class Slice(Base):
    __tablename__ = "slices"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String(100), nullable=False)
    status = Column(String(20), default="PENDING_APPROVAL")
    user = relationship("User", back_populates="slices")
    vms = relationship("VirtualMachine", back_populates="slice")

class VirtualMachine(Base):
    __tablename__ = "virtual_machines"
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, ForeignKey("slices.id"))
    name = Column(String(100), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"))
    status = Column(String(20), default="PENDING_APPROVAL")
    slice = relationship("Slice", back_populates="vms")
    worker = relationship("Worker", back_populates="vms")
