from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from app.database import Base

class VlanPool(Base):
    __tablename__ = "vlan_pool"
    vlan_id = Column(Integer, primary_key=True)
    status = Column(String(20))

class Slice(Base):
    __tablename__ = "slices"
    id = Column(Integer, primary_key=True)
    vlan_slice = Column(Integer, ForeignKey("vlan_pool.vlan_id"))

class Network(Base):
    __tablename__ = "networks"
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id"))
    vlan_inner = Column(Integer)
    subnet_cidr = Column(String(18))
    is_remote = Column(Boolean)
    internet_access = Column(Boolean)

class VmInterface(Base):
    __tablename__ = "vm_interfaces"
    id = Column(Integer, primary_key=True)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id"))
    network_id = Column(Integer, ForeignKey("networks.id"))
    mac_address = Column(String(17))
    ip_address = Column(String(15))
    interface_name = Column(String(20))
    tap_name = Column(String(30))

class VirtualMachine(Base):
    __tablename__ = "virtual_machines"
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id"))
    worker_id = Column(Integer)

class SecurityRule(Base):
    __tablename__ = "security_rules"
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, ForeignKey("slices.id"))
    src_vm_id = Column(Integer, ForeignKey("virtual_machines.id"))
    dst_vm_id = Column(Integer, ForeignKey("virtual_machines.id"))
    protocol = Column(String(10))
    port_min = Column(Integer, nullable=True)
    port_max = Column(Integer, nullable=True)
    action = Column(String(10))
    priority = Column(Integer)
