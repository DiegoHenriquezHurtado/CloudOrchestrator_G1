from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON, Text, DateTime, DECIMAL
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class Worker(Base):
    __tablename__ = "workers"
    id = Column(Integer, primary_key=True)
    hostname = Column(String(50), nullable=False)
    ip_management = Column(String(15), nullable=False)
    total_ram = Column(Integer, nullable=False)
    total_cpu = Column(Integer, nullable=False)
    current_cpu_load = Column(DECIMAL(5, 2), default=0.0)
    current_ram_available = Column(Integer, default=0)
    status = Column(String(20), default="ALIVE")
    cluster_type = Column(String(20), default="linux")
    updated_at = Column(DateTime, default=datetime.utcnow)


class Slice(Base):
    __tablename__ = "slices"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    name = Column(String(100), nullable=False)
    vlan_slice = Column(Integer)
    topology = Column(JSON)
    status = Column(String(20), default="PENDING_APPROVAL")
    iaas_target = Column(String(20), default="linux")
    created_at = Column(DateTime, default=datetime.utcnow)


class VirtualMachine(Base):
    __tablename__ = "virtual_machines"
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    base_image = Column(String(100), nullable=False)
    ram = Column(Integer, nullable=False)
    vcpu = Column(Integer, nullable=False)
    disk = Column(Integer, nullable=True)
    flavor = Column(String(100), nullable=True)
    worker_id = Column(Integer, ForeignKey("workers.id"))
    process_id = Column(Integer)
    vnc_port = Column(Integer)
    instance_path = Column(String(255))
    status = Column(String(20), default="PENDING_APPROVAL")
    vnc_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Network(Base):
    __tablename__ = "networks"
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    vlan_inner = Column(Integer, nullable=False)
    is_remote = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class VmInterface(Base):
    __tablename__ = "vm_interfaces"
    id = Column(Integer, primary_key=True)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id", ondelete="CASCADE"))
    network_id = Column(Integer, ForeignKey("networks.id", ondelete="CASCADE"), nullable=True)
    mac_address = Column(String(17))
    interface_name = Column(String(20))
    tap_name = Column(String(30))
    bridge_name = Column(String(30), nullable=True)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    vm_id = Column(Integer, ForeignKey("virtual_machines.id", ondelete="CASCADE"))
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default="PENDING")
    payload = Column(JSON, nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"))
    error_msg = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
