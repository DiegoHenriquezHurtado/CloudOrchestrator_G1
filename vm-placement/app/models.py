from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, DECIMAL, TIMESTAMP
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    quota_ram = Column(Integer)
    quota_cpu = Column(Integer)


class Slice(Base):
    __tablename__ = "slices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String)


class Worker(Base):
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True)
    status = Column(String)
    total_ram = Column(Integer)
    total_cpu = Column(Integer)
    current_ram_available = Column(Integer)
    current_cpu_load = Column(DECIMAL)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id"))
    slice_id = Column(Integer, ForeignKey("slices.id"))
    status = Column(String)
    task_type = Column(String)
    worker_id = Column(Integer, ForeignKey("workers.id"))
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class VirtualMachine(Base):
    __tablename__ = "virtual_machines"

    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id"))
    worker_id = Column(Integer)
    ram = Column(Integer)
    vcpu = Column(Integer)


class Config(Base):
    __tablename__ = "config"

    key = Column(String, primary_key=True)
    value = Column(String)
