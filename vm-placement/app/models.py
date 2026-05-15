from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, DECIMAL

Base = declarative_base()


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
    slice_id = Column(Integer)
    status = Column(String)
    task_type = Column(String)


class VirtualMachine(Base):
    __tablename__ = "virtual_machines"

    id = Column(Integer, primary_key=True)
    worker_id = Column(Integer)
    ram = Column(Integer)
    vcpu = Column(Integer)


class Config(Base):
    __tablename__ = "config"

    key = Column(String, primary_key=True)
    value = Column(String)
