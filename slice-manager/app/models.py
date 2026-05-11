from sqlalchemy import Column, Integer, String, ForeignKey, JSON, DECIMAL, DateTime
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    role = Column(String(20), default='STUDENT')
    admin_id = Column(Integer, ForeignKey('users.id'))

class Slice(Base):
    __tablename__ = 'slices'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String(100), nullable=False)
    status = Column(String(20), default='PENDING_APPROVAL')

class VirtualMachine(Base):
    __tablename__ = 'virtual_machines'
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey('slices.id'))
    name = Column(String(100), nullable=False)
    base_image = Column(String(100), nullable=False)
    ram = Column(Integer, nullable=False)
    vcpu = Column(Integer, nullable=False)
    worker_id = Column(Integer)
    process_id = Column(Integer)
    vnc_port = Column(Integer)
    instance_path = Column(String(255))
    status = Column(String(20), default='PENDING_APPROVAL')

class Network(Base):
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey('slices.id'))
    vlan_id = Column(Integer)
    subnet_cidr = Column(String(18))

class VmInterface(Base):
    __tablename__ = 'vm_interfaces'
    id = Column(Integer, primary_key=True)
    vm_id = Column(Integer, ForeignKey('virtual_machines.id'))
    network_id = Column(Integer, ForeignKey('networks.id'))
    mac_address = Column(String(17))
    ip_address = Column(String(15))
    interface_name = Column(String(20))
    tap_name = Column(String(30))

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey('slices.id'))
    vm_id = Column(Integer, ForeignKey('virtual_machines.id'))
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default='PENDING')
    payload = Column(JSON, nullable=False)
    worker_id = Column(Integer)
    error_msg = Column(String)
