from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)

class Slice(Base):
    __tablename__ = 'slices'
    id = Column(Integer, primary_key=True)

class VirtualMachine(Base):
    __tablename__ = 'virtual_machines'
    id = Column(Integer, primary_key=True)
    slice_id = Column(Integer, nullable=False)
    name = Column(String(100))
    base_image = Column(String(100))
    ram = Column(Integer)
    vcpu = Column(Integer)
    status = Column(String(20))


class VlanPool(Base):
    __tablename__ = 'vlan_pool'
    vlan_id = Column(Integer, primary_key=True)
    status = Column(String(20), default='AVAILABLE')

class Network(Base):
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, nullable=False)
    vlan_slice = Column(Integer, ForeignKey('vlan_pool.vlan_id'))  # transporte inter-worker
    vlan_inner = Column(Integer, nullable=False)                    # etiqueta local al Br-Slice
    subnet_cidr = Column(String(18))
    bridge_name = Column(String(30))
    is_remote = Column(Boolean, default=False)
    internet_access = Column(Boolean, default=False)

class VmInterface(Base):
    __tablename__ = 'vm_interfaces'
    id = Column(Integer, primary_key=True, index=True)
    vm_id = Column(Integer, nullable=False)
    network_id = Column(Integer, ForeignKey('networks.id'))
    worker_id = Column(Integer, nullable=True)
    mac_address = Column(String(17))
    ip_address = Column(String(15))
    interface_name = Column(String(20))
    tap_name = Column(String(30))

class SecurityRule(Base):
    __tablename__ = 'security_rules'
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, ForeignKey('slices.id'), nullable=False)
    src_vm_id = Column(Integer, ForeignKey('virtual_machines.id'), nullable=False)
    dst_vm_id = Column(Integer, ForeignKey('virtual_machines.id'), nullable=False)
    protocol = Column(String(10), default='any')  # tcp, udp, icmp, any
    port_min = Column(Integer, nullable=True)
    port_max = Column(Integer, nullable=True)
    action = Column(String(10), default='ALLOW')  # ALLOW, DENY
    priority = Column(Integer, default=100)
