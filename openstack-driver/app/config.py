import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ACCESS_NODE_IP: str = "10.20.11.231"
    KEYSTONE_PORT: str = "5000"
    NOVA_PORT: str = "8774"
    NEUTRON_PORT: str = "9696"
    GLANCE_PORT: str = "9292"
    DOMAIN_ID: str = "ff80f00b054f4c4abd3a00d3de1bf48f"
    ADMIN_PROJECT_ID: str = "490934a931634a3ead678e446ec662d7"
    ADMIN_USER_ID: str = "72d60bd76f254eed9c9ea9a86c35df48"
    ADMIN_USER_PASSWORD: str = "66c5f106f03328bbb47bd5ec609c320e"
    ADMIN_ROLE_ID: str = "6923937f568d47ccbb178d7b14fcd1a2"
    COMPUTE_API_VERSION: str = "2.87"
    OS_PROVIDER_NETWORK_NAME: str = "external"
    MOCK_MODE: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def keystone_url(self) -> str:
        return f"http://{self.ACCESS_NODE_IP}:{self.KEYSTONE_PORT}/v3"

    @property
    def nova_url(self) -> str:
        return f"http://{self.ACCESS_NODE_IP}:{self.NOVA_PORT}/v2.1"

    @property
    def neutron_url(self) -> str:
        return f"http://{self.ACCESS_NODE_IP}:{self.NEUTRON_PORT}/v2.0"

    @property
    def glance_url(self) -> str:
        return f"http://{self.ACCESS_NODE_IP}:{self.GLANCE_PORT}/v2.0"

settings = Settings()
