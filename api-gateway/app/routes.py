from app.config import *

ROUTE_MAP = {
    "auth": AUTH_URL,
    "slices": SLICE_MANAGER_URL + "/slices",
    "flavors": SLICE_MANAGER_URL + "/flavors",
    "images": IMAGE_MANAGER_URL + "/images",
    "infra": MONITORING_URL + "/monitoring",
    "networking": NETWORKING_URL + "/networking",
    "placement": PLACEMENT_URL + "/placement"
}

ROLE_RULES = {
    "auth": [],
    "slices": ["STUDENT", "SLICE_ADMIN", "SYSTEM_ADMIN"],
    "flavors": ["STUDENT", "SLICE_ADMIN", "SYSTEM_ADMIN"],
    "images": ["STUDENT", "SLICE_ADMIN", "SYSTEM_ADMIN"],
    "infra": ["SYSTEM_ADMIN"],
    "networking": ["SYSTEM_ADMIN"],
    "placement": ["SYSTEM_ADMIN"]
}
