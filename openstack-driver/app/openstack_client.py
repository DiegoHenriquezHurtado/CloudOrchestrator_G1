import requests
import json
import logging

logger = logging.getLogger("openstack-driver.client")

class OpenStackClient:
    def __init__(self, keystone_url: str, neutron_url: str, nova_url: str, glance_url: str, compute_api_version: str, mock_mode: bool = False):
        self.keystone_url = keystone_url
        self.neutron_url = neutron_url
        self.nova_url = nova_url
        self.glance_url = glance_url
        self.compute_api_version = compute_api_version
        self.mock_mode = mock_mode

        if mock_mode:
            self._setup_mocks()

    def _setup_mocks(self):
        logger.warning("OPENSTACK_CLIENT: Corriendo en MOCK_MODE (Simulación de clúster local activada)")
        self.get_admin_token = lambda *args, **kwargs: "mock-admin-token"
        self.get_project_scoped_token = lambda *args, **kwargs: "mock-scoped-token"
        self.create_project = lambda token, domain_id, name, desc="": f"project-{name}-uuid"
        self.delete_project = lambda *args, **kwargs: None
        self.create_user = lambda token, domain_id, username, password, default_project_id=None: f"user-{username}-uuid"
        self.delete_user = lambda *args, **kwargs: None
        self.assign_role = lambda *args, **kwargs: None
        self.get_users_by_project = lambda *args, **kwargs: []
        self.get_network_by_name = lambda token, name: f"net-{name}-uuid" if name != "external" else "b850d558-e617-43b4-a407-56a025570c63"
        self.create_network = lambda token, name: f"net-{name}-uuid"
        self.delete_network = lambda *args, **kwargs: None
        self.create_subnet = lambda token, network_id, name, cidr: f"subnet-{name}-uuid"
        self.create_port = lambda token, name, network_id, project_id: f"port-{name}-uuid"
        self.delete_port = lambda *args, **kwargs: None
        self.create_server = lambda *args, **kwargs: {"server": {"id": "mock-server-uuid"}}
        self.delete_server = lambda *args, **kwargs: None
        self.get_server = lambda token, server_id: {"status": "ACTIVE", "id": server_id}
        self.get_vnc_console = lambda token, server_id: f"http://10.20.11.231:6080/vnc_lite.html?path=%3Ftoken%3D{server_id}"
        self.get_flavor = lambda token, flavor_id: {"id": flavor_id, "ram": 2048, "vcpus": 2, "disk": 20}
        self.list_flavors = lambda token: [
            {"id": "1", "name": "m1.tiny", "ram": 512, "vcpus": 1, "disk": 1},
            {"id": "2", "name": "m1.small", "ram": 2048, "vcpus": 1, "disk": 20},
            {"id": "3", "name": "m1.medium", "ram": 4096, "vcpus": 2, "disk": 40},
        ]
        self.list_images = lambda token: [
            {"id": "img-cirros-uuid", "name": "cirros-0.6.2", "status": "active", "size": 16300000},
            {"id": "img-ubuntu-uuid", "name": "ubuntu-22.04", "status": "active", "size": 700000000},
        ]

    def _check(self, response: requests.Response, expected_status: int, op_name: str):
        if response.status_code != expected_status:
            logger.error(f"[{op_name}] Expected {expected_status}, got {response.status_code}: {response.text}")
            raise Exception(f"OpenStack API {op_name} failed: HTTP {response.status_code} - {response.text}")
        return response

    # --- KEYSTONE ---

    def get_admin_token(self, domain_id: str, admin_project_id: str, admin_user_id: str, password: str) -> str:
        url = f"{self.keystone_url}/auth/tokens"
        data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "id": admin_user_id,
                            "domain": {"id": domain_id},
                            "password": password
                        }
                    }
                },
                "scope": {
                    "project": {
                        "domain": {"id": domain_id},
                        "id": admin_project_id
                    }
                }
            }
        }
        headers = {"Content-Type": "application/json"}
        res = requests.post(url, json=data, headers=headers, timeout=10)
        self._check(res, 201, "get_admin_token")
        return res.headers["X-Subject-Token"]

    def get_project_scoped_token(self, domain_id: str, project_id: str, token: str) -> str:
        url = f"{self.keystone_url}/auth/tokens"
        data = {
            "auth": {
                "identity": {
                    "methods": ["token"],
                    "token": {"id": token}
                },
                "scope": {
                    "project": {
                        "domain": {"id": domain_id},
                        "id": project_id
                    }
                }
            }
        }
        headers = {"Content-Type": "application/json"}
        res = requests.post(url, json=data, headers=headers, timeout=10)
        self._check(res, 201, "get_project_scoped_token")
        return res.headers["X-Subject-Token"]

    def create_project(self, token: str, domain_id: str, name: str, description: str = "") -> str:
        url = f"{self.keystone_url}/projects"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        data = {
            "project": {
                "name": name,
                "description": description,
                "domain_id": domain_id
            }
        }
        res = requests.post(url, json=data, headers=headers, timeout=10)
        self._check(res, 201, "create_project")
        return res.json()["project"]["id"]

    def create_user(self, token: str, domain_id: str, username: str, password: str, default_project_id: str = None) -> str:
        url = f"{self.keystone_url}/users"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        user_data = {
            "name": username,
            "domain_id": domain_id,
            "password": password,
            "enabled": True
        }
        if default_project_id:
            user_data["default_project_id"] = default_project_id
        res = requests.post(url, json={"user": user_data}, headers=headers, timeout=10)
        self._check(res, 201, "create_user")
        return res.json()["user"]["id"]

    def assign_role(self, token: str, project_id: str, user_id: str, role_id: str):
        url = f"{self.keystone_url}/projects/{project_id}/users/{user_id}/roles/{role_id}"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        res = requests.put(url, headers=headers, timeout=10)
        self._check(res, 204, "assign_role")

    def delete_user(self, token: str, user_id: str):
        url = f"{self.keystone_url}/users/{user_id}"
        headers = {"X-Auth-Token": token}
        res = requests.delete(url, headers=headers, timeout=10)
        self._check(res, 204, "delete_user")

    def delete_project(self, token: str, project_id: str):
        url = f"{self.keystone_url}/projects/{project_id}"
        headers = {"X-Auth-Token": token}
        res = requests.delete(url, headers=headers, timeout=10)
        self._check(res, 204, "delete_project")

    def list_projects(self, token: str) -> list:
        url = f"{self.keystone_url}/projects"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=10)
        self._check(res, 200, "list_projects")
        return res.json().get("projects", [])

    def list_users(self, token: str) -> list:
        url = f"{self.keystone_url}/users"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=10)
        self._check(res, 200, "list_users")
        return res.json().get("users", [])

    # --- NEUTRON ---

    def get_network_by_name(self, token: str, name: str) -> str:
        url = f"{self.neutron_url}/networks?name={name}"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "get_network_by_name")
        networks = res.json().get("networks", [])
        if networks:
            return networks[0]["id"]
        return ""

    def create_network(self, token: str, name: str) -> str:
        url = f"{self.neutron_url}/networks"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        data = {
            "network": {
                "name": name,
                "port_security_enabled": False
            }
        }
        res = requests.post(url, json=data, headers=headers, timeout=15)
        self._check(res, 201, "create_network")
        return res.json()["network"]["id"]

    def create_subnet(self, token: str, network_id: str, name: str, cidr: str) -> str:
        url = f"{self.neutron_url}/subnets"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        data = {
            "subnet": {
                "network_id": network_id,
                "name": name,
                "ip_version": 4,
                "cidr": cidr,
                "enable_dhcp": False
            }
        }
        res = requests.post(url, json=data, headers=headers, timeout=15)
        self._check(res, 201, "create_subnet")
        return res.json()["subnet"]["id"]

    def create_port(self, token: str, name: str, network_id: str, project_id: str) -> str:
        url = f"{self.neutron_url}/ports"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        data = {
            "port": {
                "name": name,
                "tenant_id": project_id,
                "network_id": network_id,
                "port_security_enabled": False
            }
        }
        res = requests.post(url, json=data, headers=headers, timeout=15)
        self._check(res, 201, "create_port")
        return res.json()["port"]["id"]

    def delete_port(self, token: str, port_id: str):
        url = f"{self.neutron_url}/ports/{port_id}"
        headers = {"X-Auth-Token": token}
        res = requests.delete(url, headers=headers, timeout=15)
        self._check(res, 204, "delete_port")

    def delete_subnet(self, token: str, subnet_id: str):
        url = f"{self.neutron_url}/subnets/{subnet_id}"
        headers = {"X-Auth-Token": token}
        res = requests.delete(url, headers=headers, timeout=15)
        self._check(res, 204, "delete_subnet")

    def delete_network(self, token: str, network_id: str):
        url = f"{self.neutron_url}/networks/{network_id}"
        headers = {"X-Auth-Token": token}
        res = requests.delete(url, headers=headers, timeout=15)
        self._check(res, 204, "delete_network")

    def list_ports(self, token: str, project_id: str) -> list:
        url = f"{self.neutron_url}/ports?tenant_id={project_id}"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "list_ports")
        return res.json().get("ports", [])

    def list_subnets(self, token: str, project_id: str) -> list:
        url = f"{self.neutron_url}/subnets?tenant_id={project_id}"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "list_subnets")
        return res.json().get("subnets", [])

    def list_networks(self, token: str, project_id: str) -> list:
        url = f"{self.neutron_url}/networks?tenant_id={project_id}"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "list_networks")
        return res.json().get("networks", [])

    # --- NOVA ---

    def create_server(self, token: str, name: str, flavor_ref: str, image_ref: str, port_ids: list, host: str = None) -> dict:
        url = f"{self.nova_url}/servers"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token
        }
        networks = [{"port": pid} for pid in port_ids]
        data = {
            "server": {
                "name": name,
                "flavorRef": flavor_ref,
                "imageRef": image_ref,
                "networks": networks
            }
        }
        if host:
            data["server"]["availability_zone"] = f"nova:{host}"
            
        res = requests.post(url, json=data, headers=headers, timeout=20)
        self._check(res, 202, "create_server")
        return res.json()

    def get_server(self, token: str, server_id: str) -> dict:
        url = f"{self.nova_url}/servers/{server_id}"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "get_server")
        return res.json().get("server", {})

    def delete_server(self, token: str, server_id: str):
        url = f"{self.nova_url}/servers/{server_id}"
        headers = {"X-Auth-Token": token}
        res = requests.delete(url, headers=headers, timeout=15)
        self._check(res, 204, "delete_server")

    def get_vnc_console(self, token: str, server_id: str) -> str:
        url = f"{self.nova_url}/servers/{server_id}/remote-consoles"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token,
            "OpenStack-API-Version": f"compute {self.compute_api_version}"
        }
        data = {
            "remote_console": {
                "protocol": "vnc",
                "type": "novnc"
            }
        }
        res = requests.post(url, json=data, headers=headers, timeout=15)
        self._check(res, 200, "get_vnc_console")
        return res.json().get("remote_console", {}).get("url", "")

    def list_servers(self, token: str, project_id: str) -> list:
        # Petición a Nova para listar servidores de este tenant.
        # Si se hace con scoped token, no se necesita project_id query param
        url = f"{self.nova_url}/servers"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "list_servers")
        return res.json().get("servers", [])

    def get_flavor(self, token: str, flavor_id: str) -> dict:
        url = f"{self.nova_url}/flavors/{flavor_id}"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "get_flavor")
        return res.json().get("flavor", {})

    def list_flavors(self, token: str) -> list:
        url = f"{self.nova_url}/flavors/detail"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "list_flavors")
        return res.json().get("flavors", [])

    # --- GLANCE ---

    def list_images(self, token: str) -> list:
        url = f"{self.glance_url}/images"
        headers = {"X-Auth-Token": token}
        res = requests.get(url, headers=headers, timeout=15)
        self._check(res, 200, "list_images")
        return res.json().get("images", [])
