import os
import asyncssh
from typing import Dict, Any

SSH_ENABLED = os.getenv("SSH_ENABLED", "true").lower() == "true"
SSH_USER = "ubuntu"

async def get_worker_metrics(ip: str) -> Dict[str, Any]:
    if not SSH_ENABLED:
        # In local testing without SSH, return empty or default behavior
        return {}
    
    try:
        # For security and simplicity in local/VPN testing, known_hosts=None
        async with asyncssh.connect(ip, username=SSH_USER, known_hosts=None) as conn:
            # Memory metrics (in MB)
            result_mem = await conn.run("free -m", check=True)
            lines = result_mem.stdout.strip().split('\n')
            mem_line = lines[1].split()
            total_ram = int(mem_line[1])
            # Depending on free version, available could be the last column
            current_ram_available = int(mem_line[-1]) if len(mem_line) >= 7 else int(mem_line[3])

            # CPU total cores
            result_cpu = await conn.run("nproc", check=True)
            total_cpu = int(result_cpu.stdout.strip())

            # CPU Load average (1 min)
            result_load = await conn.run("cat /proc/loadavg", check=True)
            load_line = result_load.stdout.split()
            load_1m = float(load_line[0])

            # Convert to percentage
            cpu_pct = (load_1m / total_cpu) * 100 if total_cpu > 0 else 0.0
            # Cap at 100% just in case of high load
            cpu_pct = min(cpu_pct, 100.0)

            return {
                "total_ram": total_ram,
                "total_cpu": total_cpu,
                "current_cpu_load": round(cpu_pct, 2),
                "current_ram_available": current_ram_available,
                "status": "ALIVE"
            }
    except Exception as e:
        print(f"Error fetching metrics for {ip}: {e}")
        return {
            "status": "DOWN"
        }
