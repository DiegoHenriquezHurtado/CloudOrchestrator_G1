"""
SSH Client — Abstracción para ejecución remota en Workers.

Cuando SSH_ENABLED=false, simula la ejecución y retorna resultados mock
para pruebas sin Workers reales.
"""

import os
import asyncio
import logging
import random
from typing import List, Dict, Optional

logger = logging.getLogger("driver.ssh")

SSH_ENABLED = os.getenv("SSH_ENABLED", "true").lower() == "true"
SSH_USER = os.getenv("SSH_USER", "ubuntu")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "/root/.ssh/id_rsa")
SSH_TIMEOUT = int(os.getenv("SSH_TIMEOUT", "30"))
SSH_BASTION_HOST = os.getenv("SSH_BASTION_HOST", "192.168.203.4")


class CommandResult:
    """Resultado de un comando SSH."""
    def __init__(self, command: str, stdout: str = "", stderr: str = "", exit_code: int = 0):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.success = exit_code == 0

    def __repr__(self):
        return f"CommandResult(cmd='{self.command[:50]}', exit={self.exit_code})"


async def execute_on_worker(worker_ip: str, commands: List[str]) -> List[CommandResult]:
    """
    Ejecuta una lista de comandos en un Worker vía SSH.
    Retorna lista de CommandResult. Se detiene ante el primer fallo.
    """
    if not SSH_ENABLED:
        return await _mock_execute(commands)

    return await _ssh_execute(worker_ip, commands)


async def _ssh_execute(worker_ip: str, commands: List[str]) -> List[CommandResult]:
    """Ejecución real via AsyncSSH."""
    try:
        import asyncssh
    except ImportError:
        logger.error("asyncssh not installed")
        return [CommandResult(cmd, stderr="asyncssh not installed", exit_code=1) for cmd in commands]

    results = []
    try:
        # Intentar con clave SSH; si no existe, fallback a password
        connect_kwargs = {
            "host": worker_ip,
            "username": SSH_USER,
            "known_hosts": None,
        }
        if os.path.exists(SSH_KEY_PATH):
            connect_kwargs["client_keys"] = [SSH_KEY_PATH]
        else:
            connect_kwargs["password"] = os.getenv("SSH_PASSWORD", "ubuntu")

        # Si hay Bastion configurado y el objetivo no es el propio Bastion ni local
        if SSH_BASTION_HOST and worker_ip not in [SSH_BASTION_HOST, "localhost", "127.0.0.1"]:
            bastion_kwargs = connect_kwargs.copy()
            bastion_kwargs["host"] = SSH_BASTION_HOST
            logger.debug(f"Connecting to bastion {SSH_BASTION_HOST} for tunneling to {worker_ip}")
            async with asyncssh.connect(**bastion_kwargs) as bastion_conn:
                target_kwargs = connect_kwargs.copy()
                target_kwargs["tunnel"] = bastion_conn
                async with asyncssh.connect(**target_kwargs) as conn:
                    await _run_commands_on_conn(conn, worker_ip, commands, results)
        else:
            async with asyncssh.connect(**connect_kwargs) as conn:
                await _run_commands_on_conn(conn, worker_ip, commands, results)

    except Exception as e:
        logger.error(f"SSH connection to {worker_ip} failed: {e}")
        results.append(CommandResult(
            commands[len(results)] if len(results) < len(commands) else "connection",
            stderr=str(e),
            exit_code=1
        ))

    return results


async def _run_commands_on_conn(conn, worker_ip: str, commands: List[str], results: List[CommandResult]):
    """Ejecuta la lista de comandos en una conexión activa."""
    for cmd in commands:
        logger.info(f"[{worker_ip}] $ {cmd}")
        try:
            result = await asyncio.wait_for(
                conn.run(cmd, check=False),
                timeout=SSH_TIMEOUT
            )
            cr = CommandResult(
                command=cmd,
                stdout=result.stdout.strip() if result.stdout else "",
                stderr=result.stderr.strip() if result.stderr else "",
                exit_code=result.exit_status or 0,
            )
            results.append(cr)

            if cr.exit_code != 0:
                logger.warning(f"[{worker_ip}] Command failed (exit={cr.exit_code}): {cmd}")
                logger.warning(f"  stderr: {cr.stderr[:200]}")
                break  # Detener ante fallo

        except asyncio.TimeoutError:
            results.append(CommandResult(cmd, stderr="Timeout", exit_code=124))
            break


async def _mock_execute(commands: List[str]) -> List[CommandResult]:
    """Modo simulado para testing sin Workers reales."""
    results = []
    for cmd in commands:
        logger.info(f"[MOCK] $ {cmd}")

        stdout = ""
        # Simular salida de 'cat /tmp/*.pid'
        if cmd.startswith("cat /tmp/") and cmd.endswith(".pid"):
            stdout = str(random.randint(10000, 99999))

        results.append(CommandResult(command=cmd, stdout=stdout, exit_code=0))

    # Simular latencia mínima
    await asyncio.sleep(0.1)
    return results
