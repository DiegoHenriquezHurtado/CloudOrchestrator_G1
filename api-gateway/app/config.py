import os

AUTH_URL = os.getenv("AUTH_URL", "http://auth:8081")
SLICE_MANAGER_URL = os.getenv("SLICE_MANAGER_URL", "http://slice-manager:8082")
IMAGE_MANAGER_URL = os.getenv("IMAGE_MANAGER_URL", "http://image-manager:8083")
MONITORING_URL = os.getenv("MONITORING_URL", "http://monitoring:8084")
NETWORKING_URL = os.getenv("NETWORKING_URL", "http://networking:8085")
PLACEMENT_URL = os.getenv("PLACEMENT_URL", "http://vm-placement:8086")

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

MAX_BODY_SIZE = 2 * 1024 * 1024
