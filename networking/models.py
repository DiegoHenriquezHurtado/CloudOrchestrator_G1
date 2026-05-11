from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base

class VlanPool(Base):
    __tablename__ = 'vlan_pool'
    vlan_id = Column(Integer, primary_key=True)
    status = Column(String(20), default='AVAILABLE')

class Network(Base):
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, nullable=False)
    vlan_id = Column(Integer, ForeignKey('vlan_pool.vlan_id'))
    subnet_cidr = Column(String(18))

class VmInterface(Base):
    __tablename__ = 'vm_interfaces'
    id = Column(Integer, primary_key=True, index=True)
    vm_id = Column(Integer, nullable=False)
    network_id = Column(Integer, ForeignKey('networks.id'))
    mac_address = Column(String(17))
    ip_address = Column(String(15))
    interface_name = Column(String(20))
    tap_name = Column(String(30))
