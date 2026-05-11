import random
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Dict

from database import get_db
from models import VlanPool, Network, VmInterface
from schemas import AllocateRequest, ReleaseRequest

app = FastAPI(title="Networking Module")

def generate_mac():
    mac = [0x52, 0x54, 0x00, random.randint(0x00, 0x7f), random.randint(0x00, 0xff), random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))

@app.post("/networking/allocate")
async def allocate_network(request: AllocateRequest, db: AsyncSession = Depends(get_db)):
    num_networks = len(request.networks)
    
    if num_networks == 0:
        return {"status": "success", "slice_id": request.slice_id, "plan": {"networks": [], "vms": []}}
        
    result = await db.execute(select(VlanPool).where(VlanPool.status == 'AVAILABLE').limit(num_networks))
    available_vlans = result.scalars().all()
    
    if len(available_vlans) < num_networks:
        raise HTTPException(status_code=400, detail="Not enough VLANs available")
        
    network_map = {}
    network_responses = []
    
    for i, net_req in enumerate(request.networks):
        vlan = available_vlans[i]
        vlan.status = 'USED'
        db.add(vlan)
        
        subnet = f"192.168.{vlan.vlan_id}.0/24"
        new_net = Network(slice_id=request.slice_id, vlan_id=vlan.vlan_id, subnet_cidr=subnet)
        db.add(new_net)
        await db.flush()
        
        network_map[net_req.name] = {
            "id": new_net.id,
            "vlan_id": vlan.vlan_id,
            "subnet_base": f"192.168.{vlan.vlan_id}"
        }
        network_responses.append({"name": net_req.name, "vlan_id": vlan.vlan_id, "subnet_cidr": subnet})
        
    vm_responses = []
    ip_counters = {net_name: 10 for net_name in network_map.keys()}
    
    for vm in request.vms:
        ifaces_resp = []
        for iface in vm.interfaces:
            net_info = network_map.get(iface.network_name)
            if not net_info:
                raise HTTPException(status_code=400, detail=f"Network {iface.network_name} not defined in request")
                
            ip_suffix = ip_counters[iface.network_name]
            ip_counters[iface.network_name] += 1
            ip_addr = f"{net_info['subnet_base']}.{ip_suffix}"
            mac_addr = generate_mac()
            tap_name = f"tap-{vm.vm_id}-{iface.interface_name}"
            
            new_iface = VmInterface(
                vm_id=vm.vm_id,
                network_id=net_info['id'],
                mac_address=mac_addr,
                ip_address=ip_addr,
                interface_name=iface.interface_name,
                tap_name=tap_name
            )
            db.add(new_iface)
            ifaces_resp.append({
                "interface_name": iface.interface_name,
                "mac_address": mac_addr,
                "ip_address": ip_addr,
                "tap_name": tap_name,
                "vlan_id": net_info["vlan_id"]
            })
        vm_responses.append({
            "vm_id": vm.vm_id,
            "interfaces": ifaces_resp
        })
        
    await db.commit()
    
    return {
        "status": "success",
        "slice_id": request.slice_id,
        "plan": {
            "networks": network_responses,
            "vms": vm_responses
        }
    }

@app.post("/networking/release")
async def release_network(request: ReleaseRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Network).where(Network.slice_id == request.slice_id))
    networks = result.scalars().all()
    
    vlan_ids = [net.vlan_id for net in networks]
    
    if vlan_ids:
        await db.execute(update(VlanPool).where(VlanPool.vlan_id.in_(vlan_ids)).values(status='AVAILABLE'))
        
    for net in networks:
        await db.delete(net)
        
    await db.commit()
    return {"status": "success", "message": f"Released {len(vlan_ids)} VLANs for slice {request.slice_id}"}

@app.get("/networking/vlans/available")
async def get_available_vlans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VlanPool).where(VlanPool.status == 'AVAILABLE'))
    vlans = result.scalars().all()
    return {"available": len(vlans)}
