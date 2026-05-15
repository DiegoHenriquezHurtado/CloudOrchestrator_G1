from app.config import *

ROUTE_MAP = {
    "auth": AUTH_URL,
    "slices": SLICE_MANAGER_URL,
    "images": IMAGE_MANAGER_URL,
    "infra": MONITORING_URL,
    "networking": NETWORKING_URL,
    "placement": PLACEMENT_URL
}

ROLE_RULES = {
    "auth": [],
    "slices": ["STUDENT", "SLICE_ADMIN", "SYSTEM_ADMIN"],
    "images": ["STUDENT", "SLICE_ADMIN", "SYSTEM_ADMIN"],
    "infra": ["SYSTEM_ADMIN"],
    "networking": ["SYSTEM_ADMIN"],
    "placement": ["SYSTEM_ADMIN"]
}
