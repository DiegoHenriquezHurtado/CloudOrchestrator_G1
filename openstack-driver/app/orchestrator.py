import asyncio
import logging
from typing import Dict, Any, List

from app.config import Settings
from app.openstack_client import OpenStackClient
from app.schemas import (
    CreateSliceRequest,
    CreateSliceResponse,
    VmDeployDetail,
    VmCreatePayload,
    NetworkCreatePayload
)

logger = logging.getLogger("openstack-driver.orchestrator")

class OpenStackOrchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenStackClient(
            keystone_url=settings.keystone_url,
            neutron_url=settings.neutron_url,
            nova_url=settings.nova_url,
            glance_url=settings.glance_url,
            compute_api_version=settings.COMPUTE_API_VERSION,
            mock_mode=settings.MOCK_MODE
        )

    async def _get_admin_token(self) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self.client.get_admin_token,
            self.settings.DOMAIN_ID,
            self.settings.ADMIN_PROJECT_ID,
            self.settings.ADMIN_USER_ID,
            self.settings.ADMIN_USER_PASSWORD
        )

    async def check_api_connectivity(self) -> bool:
        """Chequea si la API de OpenStack responde autenticando al admin"""
        try:
            # Intentar obtener el token de administrador
            loop = asyncio.get_running_loop()
            token = await loop.run_in_executor(
                None,
                self.client.get_admin_token,
                self.settings.DOMAIN_ID,
                self.settings.ADMIN_PROJECT_ID,
                self.settings.ADMIN_USER_ID,
                self.settings.ADMIN_USER_PASSWORD
            )
            return token != ""
        except Exception as e:
            logger.error(f"OpenStack API connectivity check failed: {e}")
            return False

    async def get_flavor(self, flavor_id: str) -> dict:
        """Obtiene detalles de un flavor desde Nova"""
        loop = asyncio.get_running_loop()
        admin_token = await loop.run_in_executor(
            None,
            self.client.get_admin_token,
            self.settings.DOMAIN_ID,
            self.settings.ADMIN_PROJECT_ID,
            self.settings.ADMIN_USER_ID,
            self.settings.ADMIN_USER_PASSWORD
        )
        flavor = await loop.run_in_executor(
            None,
            self.client.get_flavor,
            admin_token,
            flavor_id
        )
        return flavor

    async def list_flavors(self) -> list:
        """Lista los flavors disponibles en Nova (id, nombre, ram, vcpus, disk)"""
        admin_token = await self._get_admin_token()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.client.list_flavors, admin_token)

    async def list_images(self) -> list:
        """Lista las imágenes disponibles en Glance (id, nombre, estado)"""
        admin_token = await self._get_admin_token()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.client.list_images, admin_token)

    async def upload_image(self, name: str, disk_format: str, container_format: str, visibility: str, upload_file) -> dict:
        """
        Registra e importa una imagen de disco en Glance de forma independiente
        de la plataforma que la generó (Linux/QEMU, OpenStack, etc).

        Primero registra los metadatos y luego transmite el archivo en streaming
        (sin cargarlo completo en memoria) hacia Glance. Si la subida de datos
        falla, se elimina el registro de metadatos huérfano.
        """
        loop = asyncio.get_running_loop()
        admin_token = await self._get_admin_token()

        image_id = await loop.run_in_executor(
            None,
            self.client.create_image,
            admin_token,
            name,
            disk_format,
            container_format,
            visibility
        )

        try:
            await loop.run_in_executor(
                None,
                self.client.upload_image_data,
                admin_token,
                image_id,
                upload_file.file
            )
        except Exception as e:
            logger.error(f"Fallo subiendo datos de la imagen '{name}' ({image_id}), limpiando registro huérfano: {e}")
            try:
                await loop.run_in_executor(None, self.client.delete_image, admin_token, image_id)
            except Exception as cleanup_err:
                logger.error(f"No se pudo limpiar la imagen huérfana {image_id}: {cleanup_err}")
            raise

        return {"id": image_id, "name": name, "status": "uploaded"}

    async def delete_image(self, image_id: str) -> None:
        """Elimina una imagen de Glance (borrado seguro tras validación)"""
        admin_token = await self._get_admin_token()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.client.delete_image, admin_token, image_id)

    async def provision_slice(self, req: CreateSliceRequest) -> CreateSliceResponse:
        """
        Orquesta de forma atómica la creación de un Slice en OpenStack.
        
        Si ocurre un error durante el despliegue de cualquier recurso, se
        lanza una excepción y se ejecuta la rutina de rollback inverso de inmediato.
        """
        try:
            return await self._provision_slice_raw(req)
        except Exception as e:
            logger.error(f"Error en provision_slice, ejecutando rollback para {req.slice_id}: {e}")
            await self.rollback_slice(req.slice_id)
            raise e

    async def _provision_slice_raw(self, req: CreateSliceRequest) -> CreateSliceResponse:
        loop = asyncio.get_running_loop()
        
        # --- Paso 1: Autenticación Admin ---
        logger.info("Paso 1: Obteniendo token de administrador de OpenStack...")
        admin_token = await loop.run_in_executor(
            None,
            self.client.get_admin_token,
            self.settings.DOMAIN_ID,
            self.settings.ADMIN_PROJECT_ID,
            self.settings.ADMIN_USER_ID,
            self.settings.ADMIN_USER_PASSWORD
        )

        # --- Paso 2: Crear Proyecto (Tenant) en Keystone ---
        logger.info(f"Paso 2: Creando proyecto '{req.slice_id}' en OpenStack...")
        project_id = await loop.run_in_executor(
            None,
            self.client.create_project,
            admin_token,
            self.settings.DOMAIN_ID,
            req.slice_id,
            f"Proyecto de Slice académico para {req.slice_id}"
        )

        # --- Paso 3: Crear Usuario de Proyecto ---
        username = f"user_{req.slice_id}"
        password = f"pass_{req.slice_id}"
        logger.info(f"Paso 3: Creando usuario '{username}'...")
        user_id = await loop.run_in_executor(
            None,
            self.client.create_user,
            admin_token,
            self.settings.DOMAIN_ID,
            username,
            password,
            project_id
        )

        # --- Paso 4: Asignar Roles ---
        logger.info(f"Paso 4: Asignando rol admin al usuario '{username}' en el proyecto...")
        await loop.run_in_executor(
            None,
            self.client.assign_role,
            admin_token,
            project_id,
            user_id,
            self.settings.ADMIN_ROLE_ID
        )

        # --- Paso 5: Obtener scoped token ---
        logger.info(f"Paso 5: Obteniendo token con alcance (scoped token) del proyecto usando credenciales del nuevo usuario...")
        scoped_token = await loop.run_in_executor(
            None,
            self.client.get_admin_token,
            self.settings.DOMAIN_ID,
            project_id,
            user_id,
            password
        )

        # --- Paso 6: Resolver Red Provider (inmutable) ---
        logger.info(f"Paso 6: Resolviendo ID de la red Provider '{self.settings.OS_PROVIDER_NETWORK_NAME}'...")
        provider_net_id = await loop.run_in_executor(
            None,
            self.client.get_network_by_name,
            admin_token,
            self.settings.OS_PROVIDER_NETWORK_NAME
        )
        if not provider_net_id:
            raise Exception(f"Error: La red Provider externa '{self.settings.OS_PROVIDER_NETWORK_NAME}' no existe.")

        # --- Paso 7: Crear Redes y Subredes Privadas (Neutron) ---
        logger.info("Paso 7: Creando redes y subredes internas...")
        net_map = {}  # Mapeo: nombre_red -> UUID_red
        
        for net in req.networks:
            if net.is_provider:
                net_map[net.name] = provider_net_id
            else:
                logger.info(f"Creando red privada: {net.name}")
                net_id = await loop.run_in_executor(
                    None,
                    self.client.create_network,
                    scoped_token,
                    net.name
                )
                net_map[net.name] = net_id
                
                # Crear subred asociada
                if not net.cidr:
                    raise Exception(f"La red privada {net.name} requiere un CIDR definido.")
                
                logger.info(f"Creando subred para {net.name} con CIDR {net.cidr}")
                await loop.run_in_executor(
                    None,
                    self.client.create_subnet,
                    scoped_token,
                    net_id,
                    f"subnet_{net.name}",
                    net.cidr
                )

        # --- Paso 8: Crear Puertos (Ports) ---
        logger.info("Paso 8: Creando puertos lógicos...")
        vm_ports = {}  # VM name -> lista de port IDs
        
        for vm in req.vms:
            port_ids = []
            for idx, net_name in enumerate(vm.networks):
                net_id = net_map.get(net_name)
                if not net_id:
                    raise Exception(f"La red {net_name} especificada en la VM {vm.name} no está definida.")
                
                port_name = f"port_{vm.name}_{idx}"
                
                if net_id == provider_net_id:
                    # Puertos en la red Provider compartida se crean como admin pero asociados al proyecto del alumno
                    logger.info(f"Creando puerto externo '{port_name}' en red Provider...")
                    p_id = await loop.run_in_executor(
                        None,
                        self.client.create_port,
                        admin_token,
                        port_name,
                        provider_net_id,
                        project_id
                    )
                else:
                    # Puertos en redes privadas se crean con el scoped token del proyecto
                    logger.info(f"Creando puerto interno '{port_name}' en red privada '{net_name}'...")
                    p_id = await loop.run_in_executor(
                        None,
                        self.client.create_port,
                        scoped_token,
                        port_name,
                        net_id,
                        project_id
                    )
                port_ids.append(p_id)
            vm_ports[vm.name] = port_ids

        # --- Paso 9: Crear Instancias (Nova) ---
        logger.info("Paso 9: Lanzando instancias en Nova...")
        vm_details = []
        
        for vm in req.vms:
            ports = vm_ports[vm.name]
            logger.info(f"Instanciando VM '{vm.name}' con puertos {ports} en host {vm.host}...")
            server_res = await loop.run_in_executor(
                None,
                self.client.create_server,
                scoped_token,
                vm.name,
                vm.flavor,
                vm.image,
                ports,
                vm.host
            )
            server_id = server_res["server"]["id"]
            vm_details.append(VmDeployDetail(
                name=vm.name,
                server_id=server_id,
                status="BUILD"
            ))

        # --- Paso 10: Polling de Estado y VNC console ---
        logger.info("Paso 10: Esperando que las instancias inicien (ACTIVE)...")
        vms_ready = []
        
        # Hacemos polling durante máx 45 segundos (15 iteraciones x 3s)
        for i in range(15):
            await asyncio.sleep(3)
            all_active = True
            
            for vm_detail in vm_details:
                server_info = await loop.run_in_executor(
                    None,
                    self.client.get_server,
                    scoped_token,
                    vm_detail.server_id
                )
                status = server_info.get("status", "UNKNOWN")
                vm_detail.status = status
                
                if status == "ERROR":
                    fault = server_info.get("fault", {})
                    fault_msg = fault.get("message", "sin detalle de Nova")
                    raise Exception(f"La máquina virtual {vm_detail.name} falló al iniciar en OpenStack (estado: ERROR). Motivo de Nova: {fault_msg}")
                if status != "ACTIVE":
                    all_active = False
            
            if all_active:
                logger.info("Todas las máquinas virtuales están ACTIVE.")
                break
        else:
            # Si pasaron los 45s y no están ACTIVE, arrojamos timeout
            raise Exception("Timeout esperando el estado ACTIVE de las instancias de OpenStack.")

        # Obtener consolas VNC
        logger.info("Obteniendo URLs de consola noVNC...")
        for vm_detail in vm_details:
            try:
                vnc_url = await loop.run_in_executor(
                    None,
                    self.client.get_vnc_console,
                    admin_token,
                    vm_detail.server_id
                )
                vm_detail.vnc_url = vnc_url
            except Exception as e:
                logger.warning(f"No se pudo obtener consola VNC para {vm_detail.name}: {e}")
                vm_detail.vnc_url = None

        return CreateSliceResponse(
            slice_id=req.slice_id,
            status="READY",
            project_id=project_id,
            vms=vm_details,
            message="Slice de OpenStack creado con éxito."
        )

    async def rollback_slice(self, slice_id: str) -> str:
        """
        Ejecuta la destrucción automática e inversa de recursos
        cuando el aprovisionamiento de un slice falla a la mitad del flujo.
        """
        logger.warning(f"Iniciando rollback atómico de emergencia para Slice: {slice_id}")
        try:
            return await self.deprovision_slice(slice_id)
        except Exception as e:
            logger.error(f"Excepción interna durante el rollback de {slice_id}: {e}")
            return f"Error en rollback: {str(e)}"

    async def deprovision_slice(self, slice_id: str) -> str:
        """
        Destruye de forma segura y en cascada todos los recursos del Slice.
        
        REGLA CRÍTICA DE REDES: Bajo ninguna circunstancia borra la red Provider externa,
        únicamente destruye los puertos lógicos que se asociaron a este proyecto dentro de ella.
        """
        loop = asyncio.get_running_loop()
        
        # 1. Obtener Token Admin
        admin_token = await loop.run_in_executor(
            None,
            self.client.get_admin_token,
            self.settings.DOMAIN_ID,
            self.settings.ADMIN_PROJECT_ID,
            self.settings.ADMIN_USER_ID,
            self.settings.ADMIN_USER_PASSWORD
        )

        # 2. Localizar el Proyecto (Tenant) por nombre
        projects = await loop.run_in_executor(
            None,
            self.client.list_projects,
            admin_token
        )
        target_project = next((p for p in projects if p["name"] == slice_id), None)
        if not target_project:
            return "El proyecto ya no existe o no fue creado."
        
        project_id = target_project["id"]

        # Intentar resolver el scoped token usando credenciales del usuario local del proyecto
        username = f"user_{slice_id}"
        password = f"pass_{slice_id}"
        user_id = None
        try:
            users = await loop.run_in_executor(
                None,
                self.client.list_users,
                admin_token
            )
            target_user = next((u for u in users if u["name"] == username), None)
            if target_user:
                user_id = target_user["id"]
        except Exception as e:
            logger.warning(f"Error al listar usuarios en deprovision_slice: {e}")

        scoped_token = None
        if user_id:
            try:
                scoped_token = await loop.run_in_executor(
                    None,
                    self.client.get_admin_token,
                    self.settings.DOMAIN_ID,
                    project_id,
                    user_id,
                    password
                )
            except Exception as e:
                logger.warning(f"No se pudo obtener scoped token con credenciales locales de alumno: {e}")

        if not scoped_token:
            logger.info("Intentando resolver scoped token vía token re-scope del administrador como fallback...")
            scoped_token = await loop.run_in_executor(
                None,
                self.client.get_project_scoped_token,
                self.settings.DOMAIN_ID,
                project_id,
                admin_token
            )

        # Resolver ID de red provider
        provider_net_id = await loop.run_in_executor(
            None,
            self.client.get_network_by_name,
            admin_token,
            self.settings.OS_PROVIDER_NETWORK_NAME
        )

        # 3. Eliminar Instancias (Nova)
        servers = await loop.run_in_executor(
            None,
            self.client.list_servers,
            scoped_token,
            project_id
        )
        
        for server in servers:
            logger.info(f"Eliminando servidor: {server['id']}")
            await loop.run_in_executor(
                None,
                self.client.delete_server,
                scoped_token,
                server["id"]
            )

        # Esperar hasta 30s a que las instancias desaparezcan
        for _ in range(10):
            servers_left = await loop.run_in_executor(
                None,
                self.client.list_servers,
                scoped_token,
                project_id
            )
            if not servers_left:
                break
            await asyncio.sleep(3)

        # 4. Eliminar Puertos (Neutron)
        ports = await loop.run_in_executor(
            None,
            self.client.list_ports,
            admin_token,
            project_id
        )
        for port in ports:
            logger.info(f"Eliminando puerto: {port['id']} (Red: {port['network_id']})")
            await loop.run_in_executor(
                None,
                self.client.delete_port,
                admin_token,
                port["id"]
            )

        # 5. Eliminar Subredes (Neutron)
        subnets = await loop.run_in_executor(
            None,
            self.client.list_subnets,
            admin_token,
            project_id
        )
        for subnet in subnets:
            logger.info(f"Eliminando subred: {subnet['id']}")
            await loop.run_in_executor(
                None,
                self.client.delete_subnet,
                admin_token,
                subnet["id"]
            )

        # 6. Eliminar Redes Privadas (Neutron)
        networks = await loop.run_in_executor(
            None,
            self.client.list_networks,
            admin_token,
            project_id
        )
        for net in networks:
            # VALIDACIÓN DE SEGURIDAD CRÍTICA
            if net["id"] == provider_net_id or net.get("shared") or net.get("router:external"):
                logger.info(f"Red de red Provider externa detectada ({net['name']}). Saltando eliminación.")
                continue
            
            logger.info(f"Eliminando red privada: {net['id']}")
            await loop.run_in_executor(
                None,
                self.client.delete_network,
                admin_token,
                net["id"]
            )

        # 7. Eliminar Usuario en Keystone
        users = await loop.run_in_executor(
            None,
            self.client.list_users,
            admin_token
        )
        target_username = f"user_{slice_id}"
        target_user = next((u for u in users if u["name"] == target_username), None)
        if target_user:
            logger.info(f"Eliminando usuario del slice: {target_user['id']}")
            await loop.run_in_executor(
                None,
                self.client.delete_user,
                admin_token,
                target_user["id"]
            )

        # 8. Eliminar Proyecto en Keystone
        logger.info(f"Eliminando proyecto del slice: {project_id}")
        await loop.run_in_executor(
            None,
            self.client.delete_project,
            admin_token,
            project_id
        )

        return f"Proyecto {project_id} y recursos asociados eliminados."
