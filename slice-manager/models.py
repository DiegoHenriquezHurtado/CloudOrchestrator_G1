from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON, Text, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="STUDENT")
    admin_id = Column(Integer, ForeignKey("users.id"))
    quota_ram = Column(Integer, default=4096)
    quota_cpu = Column(Integer, default=4)
    created_at = Column(DateTime, default=datetime.utcnow)

class VlanPool(Base):
    __tablename__ = "vlan_pool"
    vlan_id = Column(Integer, primary_key=True)
    status = Column(String(20), default="AVAILABLE")
    updated_at = Column(DateTime, default=datetime.utcnow)

class Slice(Base):
    __tablename__ = "slices"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String(100), nullable=False)
    vlan_slice = Column(Integer, ForeignKey("vlan_pool.vlan_id"))
    topology = Column(JSON)  # Links originales de la topología (persistido para approve)
    status = Column(String(20), default="PENDING_APPROVAL")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    vms = relationship("VirtualMachine", back_populates="slice", cascade="all, delete", passive_deletes=True)
    networks = relationship("Network", back_populates="slice", cascade="all, delete", passive_deletes=True)
    tasks = relationship("Task", back_populates="slice", cascade="all, delete", passive_deletes=True)

class VirtualMachine(Base):
    __tablename__ = "virtual_machines"
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    base_image = Column(String(100), nullable=False)
    ram = Column(Integer, nullable=False)
    vcpu = Column(Integer, nullable=False)
    worker_id = Column(Integer)
    process_id = Column(Integer)
    vnc_port = Column(Integer)
    instance_path = Column(String(255))
    status = Column(String(20), default="PENDING_APPROVAL")
    created_at = Column(DateTime, default=datetime.utcnow)

    slice = relationship("Slice", back_populates="vms")
    interfaces = relationship("VmInterface", back_populates="vm", cascade="all, delete", passive_deletes=True)
    tasks = relationship("Task", back_populates="vm", cascade="all, delete", passive_deletes=True)

class Network(Base):
    __tablename__ = "networks"
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    vlan_inner = Column(Integer, nullable=False)
    subnet_cidr = Column(String(18))
    is_remote = Column(Boolean, default=False)
    internet_access = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    slice = relationship("Slice", back_populates="networks")

class VmInterface(Base):
    __tablename__ = "vm_interfaces"
    id = Column(Integer, primary_key=True, index=True)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id", ondelete="CASCADE"))
    network_id = Column(Integer, ForeignKey("networks.id", ondelete="CASCADE"))
    mac_address = Column(String(17))
    ip_address = Column(String(15))
    interface_name = Column(String(20))
    tap_name = Column(String(30))

    vm = relationship("VirtualMachine", back_populates="interfaces")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    vm_id = Column(Integer, ForeignKey("virtual_machines.id", ondelete="CASCADE"))
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default="PENDING")
    payload = Column(JSON, nullable=False)
    worker_id = Column(Integer)
    error_msg = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    slice = relationship("Slice", back_populates="tasks")
    vm = relationship("VirtualMachine", back_populates="tasks")
