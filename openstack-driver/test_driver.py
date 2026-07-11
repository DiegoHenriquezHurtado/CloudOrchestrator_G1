import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import asyncio

# Ajustar path para importar el módulo app
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.schemas import CreateSliceRequest, DeleteSliceRequest
from app.orchestrator import OpenStackOrchestrator
from app.config import settings

class TestOpenStackDriver(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.orchestrator = OpenStackOrchestrator(settings=settings)

    @patch('app.openstack_client.requests.post')
    @patch('app.openstack_client.requests.get')
    @patch('app.openstack_client.requests.put')
    async def test_provision_slice_success(self, mock_put, mock_get, mock_post):
        """Prueba de despliegue exitoso de un Slice en OpenStack"""
        
        # 1. Mock de Keystone Tokens (Admin y Scoped)
        res_admin_token = MagicMock()
        res_admin_token.status_code = 201
        res_admin_token.headers = {"X-Subject-Token": "mock-admin-token-uuid"}
        
        res_scoped_token = MagicMock()
        res_scoped_token.status_code = 201
        res_scoped_token.headers = {"X-Subject-Token": "mock-scoped-token-uuid"}
        
        # 2. Mock de creación de Proyecto y Usuario
        res_create_proj = MagicMock()
        res_create_proj.status_code = 201
        res_create_proj.json.return_value = {"project": {"id": "mock-project-uuid"}}
        
        res_create_user = MagicMock()
        res_create_user.status_code = 201
        res_create_user.json.return_value = {"user": {"id": "mock-user-uuid"}}
        
        # Post calls mapping
        # 1. admin token, 2. project, 3. user, 4. scoped token
        # 5. create network, 6. create subnet, 7. port ext, 8. port int, 9. server, 10. vnc
        res_create_net = MagicMock()
        res_create_net.status_code = 201
        res_create_net.json.return_value = {"network": {"id": "mock-private-net-uuid"}}
        
        res_create_subnet = MagicMock()
        res_create_subnet.status_code = 201
        res_create_subnet.json.return_value = {"subnet": {"id": "mock-subnet-uuid"}}
        
        res_create_port_ext = MagicMock()
        res_create_port_ext.status_code = 201
        res_create_port_ext.json.return_value = {"port": {"id": "mock-port-ext-uuid"}}
        
        res_create_port_int = MagicMock()
        res_create_port_int.status_code = 201
        res_create_port_int.json.return_value = {"port": {"id": "mock-port-int-uuid"}}
        
        res_create_server = MagicMock()
        res_create_server.status_code = 202
        res_create_server.json.return_value = {"server": {"id": "mock-server-uuid"}}
        
        res_vnc = MagicMock()
        res_vnc.status_code = 200
        res_vnc.json.return_value = {"remote_console": {"url": "http://mock-vnc-console-url"}}

        mock_post.side_effect = [
            res_admin_token,     # token admin
            res_create_proj,     # project
            res_create_user,     # user
            res_scoped_token,    # token scoped
            res_create_net,      # private network
            res_create_subnet,   # private subnet
            res_create_port_ext, # port ext
            res_create_port_int, # port int
            res_create_server,   # create server
            res_vnc              # vnc URL
        ]

        # 3. Mock de Role assignment (PUT)
        res_assign_role = MagicMock()
        res_assign_role.status_code = 204
        mock_put.return_value = res_assign_role

        # 4. Mock de GET calls
        # 1. Resolviendo red provider
        res_get_provider_net = MagicMock()
        res_get_provider_net.status_code = 200
        res_get_provider_net.json.return_value = {"networks": [{"id": "mock-provider-net-uuid"}]}
        
        # 2. Polling de servidor (Nova status checks)
        res_server_status = MagicMock()
        res_server_status.status_code = 200
        res_server_status.json.return_value = {"server": {"status": "ACTIVE"}}
        
        mock_get.side_effect = [
            res_get_provider_net, # lookup provider net
            res_server_status     # polling check
        ]

        # Configurar request del Slice
        req = CreateSliceRequest(
            slice_id="test-slice-1",
            vms=[
                {
                    "name": "instance_3",
                    "image": "mock-image-uuid",
                    "flavor": "mock-flavor-uuid",
                    "networks": ["network_link3", "external"]
                }
            ],
            networks=[
                {
                    "name": "network_link3",
                    "cidr": "192.168.3.0/30",
                    "is_provider": False
                },
                {
                    "name": "external",
                    "is_provider": True
                }
            ]
        )

        # Ejecutar provisión
        response = await self.orchestrator.provision_slice(req)

        # Aseveraciones
        self.assertEqual(response.status, "READY")
        self.assertEqual(response.slice_id, "test-slice-1")
        self.assertEqual(response.project_id, "mock-project-uuid")
        self.assertEqual(len(response.vms), 1)
        self.assertEqual(response.vms[0].server_id, "mock-server-uuid")
        self.assertEqual(response.vms[0].vnc_url, "http://mock-vnc-console-url")

    @patch('app.openstack_client.requests.post')
    @patch('app.openstack_client.requests.get')
    @patch('app.openstack_client.requests.put')
    @patch('app.orchestrator.OpenStackOrchestrator.deprovision_slice')
    async def test_provision_slice_failure_triggers_rollback(self, mock_deprovision, mock_put, mock_get, mock_post):
        """Verifica que un fallo en la API de OpenStack dispare la rutina de rollback inverso"""
        
        # Simular respuestas hasta Keystone pero fallar en Neutron Network
        res_admin_token = MagicMock()
        res_admin_token.status_code = 201
        res_admin_token.headers = {"X-Subject-Token": "mock-admin-token-uuid"}
        
        res_create_proj = MagicMock()
        res_create_proj.status_code = 201
        res_create_proj.json.return_value = {"project": {"id": "mock-project-uuid"}}
        
        res_create_user = MagicMock()
        res_create_user.status_code = 201
        res_create_user.json.return_value = {"user": {"id": "mock-user-uuid"}}
        
        res_scoped_token = MagicMock()
        res_scoped_token.status_code = 201
        res_scoped_token.headers = {"X-Subject-Token": "mock-scoped-token-uuid"}

        # Network creation fails (HTTP 400 Bad Request)
        res_create_net_failed = MagicMock()
        res_create_net_failed.status_code = 400
        res_create_net_failed.text = "Bad subnet details or quota exceeded"

        mock_post.side_effect = [
            res_admin_token,
            res_create_proj,
            res_create_user,
            res_scoped_token,
            res_create_net_failed
        ]

        res_assign_role = MagicMock()
        res_assign_role.status_code = 204
        mock_put.return_value = res_assign_role

        res_get_provider_net = MagicMock()
        res_get_provider_net.status_code = 200
        res_get_provider_net.json.return_value = {"networks": [{"id": "mock-provider-net-uuid"}]}
        mock_get.return_value = res_get_provider_net

        mock_deprovision.return_value = "Rollback ejecutado con éxito."

        req = CreateSliceRequest(
            slice_id="test-slice-failed",
            vms=[
                {
                    "name": "instance_3",
                    "image": "mock-image-uuid",
                    "flavor": "mock-flavor-uuid",
                    "networks": ["network_link3", "external"]
                }
            ],
            networks=[
                {
                    "name": "network_link3",
                    "cidr": "192.168.3.0/30",
                    "is_provider": False
                },
                {
                    "name": "external",
                    "is_provider": True
                }
            ]
        )

        # Debe lanzar una excepción
        with self.assertRaises(Exception) as context:
            await self.orchestrator.provision_slice(req)

        self.assertIn("create_network failed", str(context.exception))
        
        # El rollback debió llamarse con el ID del slice fallido
        mock_deprovision.assert_called_once_with("test-slice-failed")

    @patch('app.openstack_client.requests.post')
    @patch('app.openstack_client.requests.get')
    @patch('app.openstack_client.requests.delete')
    async def test_deprovision_slice_success_rules(self, mock_delete, mock_get, mock_post):
        """Verifica que la deprovisión limpia todo excepto la red Provider externa"""
        
        # Mocks de tokens
        res_admin_token = MagicMock()
        res_admin_token.status_code = 201
        res_admin_token.headers = {"X-Subject-Token": "mock-admin-token-uuid"}
        
        res_scoped_token = MagicMock()
        res_scoped_token.status_code = 201
        res_scoped_token.headers = {"X-Subject-Token": "mock-scoped-token-uuid"}
        
        mock_post.side_effect = [res_admin_token, res_scoped_token]

        # Mocks GET:
        # 1. list projects, 2. resolve provider name, 3. list servers, 4. check servers delete,
        # 5. list ports, 6. list subnets, 7. list networks, 8. list users
        res_list_proj = MagicMock()
        res_list_proj.status_code = 200
        res_list_proj.json.return_value = {"projects": [{"name": "test-slice-del", "id": "proj-del-uuid"}]}
        
        res_get_provider_net = MagicMock()
        res_get_provider_net.status_code = 200
        res_get_provider_net.json.return_value = {"networks": [{"id": "mock-provider-net-uuid"}]}
        
        res_list_servers = MagicMock()
        res_list_servers.status_code = 200
        res_list_servers.json.return_value = {"servers": [{"id": "server-del-uuid"}]}
        
        res_list_servers_empty = MagicMock()
        res_list_servers_empty.status_code = 200
        res_list_servers_empty.json.return_value = {"servers": []}

        res_list_ports = MagicMock()
        res_list_ports.status_code = 200
        res_list_ports.json.return_value = {"ports": [{"id": "port-del-uuid", "network_id": "mock-provider-net-uuid"}]}

        res_list_subnets = MagicMock()
        res_list_subnets.status_code = 200
        res_list_subnets.json.return_value = {"subnets": [{"id": "subnet-del-uuid"}]}

        res_list_networks = MagicMock()
        res_list_networks.status_code = 200
        res_list_networks.json.return_value = {"networks": [
            {"id": "mock-provider-net-uuid", "name": "external", "shared": True}, # PROVIDER - NO DEBE BORRARSE
            {"id": "net-del-uuid", "name": "network_link3", "shared": False}       # PRIVADA - SI SE BORRA
        ]}

        res_list_users = MagicMock()
        res_list_users.status_code = 200
        res_list_users.json.return_value = {"users": [{"name": "user_test-slice-del", "id": "user-del-uuid"}]}

        mock_get.side_effect = [
            res_list_proj,
            res_get_provider_net,
            res_list_servers,      # list servers
            res_list_servers_empty, # verify delete polling
            res_list_ports,
            res_list_subnets,
            res_list_networks,
            res_list_users
        ]

        # Mocks de DELETE
        res_del = MagicMock()
        res_del.status_code = 204
        mock_delete.return_value = res_del

        # Ejecutar deprovisión
        summary = await self.orchestrator.deprovision_slice("test-slice-del")

        # Verificar qué recursos fueron eliminados por el mock_delete
        deleted_urls = [call.args[0] for call in mock_delete.call_args_list]
        
        # Debió borrar el servidor
        self.assertTrue(any("servers/server-del-uuid" in url for url in deleted_urls))
        # Debió borrar el puerto de la red provider (borra el puerto, no la red)
        self.assertTrue(any("ports/port-del-uuid" in url for url in deleted_urls))
        # Debió borrar la subred
        self.assertTrue(any("subnets/subnet-del-uuid" in url for url in deleted_urls))
        # Debió borrar la red privada
        self.assertTrue(any("networks/net-del-uuid" in url for url in deleted_urls))
        # Debió borrar el usuario
        self.assertTrue(any("users/user-del-uuid" in url for url in deleted_urls))
        # Debió borrar el proyecto
        self.assertTrue(any("projects/proj-del-uuid" in url for url in deleted_urls))
        
        # REGLA CRÍTICA: NO debió borrar la red provider
        self.assertFalse(any(f"networks/mock-provider-net-uuid" in url for url in deleted_urls))
        self.assertIn("recursos asociados eliminados", summary)

if __name__ == '__main__':
    unittest.main()
