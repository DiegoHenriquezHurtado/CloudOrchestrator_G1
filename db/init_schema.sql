-- db/init_schema.sql
-- Diseño de Base de Datos para Orquestador Cloud - Fase 1

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'STUDENT', -- STUDENT, SLICE_ADMIN, SYSTEM_ADMIN
    admin_id INT REFERENCES users(id), -- Para asignar un STUDENT a un SLICE_ADMIN
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE flavors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    ram INT NOT NULL,
    vcpu INT NOT NULL,
    disk INT NOT NULL,
    allowed_role VARCHAR(20) DEFAULT 'STUDENT',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workers (
    id SERIAL PRIMARY KEY,
    hostname VARCHAR(50) NOT NULL,
    ip_management VARCHAR(15) NOT NULL,
    total_ram INT NOT NULL, -- en MB
    total_cpu INT NOT NULL, -- número de cores
    current_cpu_load DECIMAL(5,2) DEFAULT 0.0,
    current_ram_available INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'ALIVE', -- ALIVE o DOWN
    cluster_type VARCHAR(20) DEFAULT 'linux', -- 'linux' o 'openstack'
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vlan_pool (
    vlan_id INT PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'AVAILABLE', -- 'AVAILABLE' o 'USED'
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_vlan_range CHECK (vlan_id >= 100 AND vlan_id <= 1000)
);


CREATE TABLE slices (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    name VARCHAR(100) NOT NULL,
    vlan_slice INT REFERENCES vlan_pool(vlan_id), -- Vlan-Slice: etiqueta de transporte inter-worker (una por Slice)
    topology JSONB, -- Links originales de la topología del alumno (persistido para la fase de aprobación)
    status VARCHAR(20) DEFAULT 'PENDING_APPROVAL', -- PENDING_APPROVAL, ACTIVE, FAILED, etc.
    iaas_target VARCHAR(20) DEFAULT 'linux', -- 'linux' o 'openstack'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE virtual_machines (
    id SERIAL PRIMARY KEY,
    slice_id INT REFERENCES slices(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    base_image VARCHAR(100) NOT NULL,
    ram INT NOT NULL, -- RAM asignada
    vcpu INT NOT NULL, -- Cores asignados
    disk INT, -- Disco asignado
    flavor VARCHAR(100), -- Sabor en OpenStack (Fase 2)
    flavor_id INT REFERENCES flavors(id), -- Flavor Linux original (para exportar/reimportar la topología fielmente)
    worker_id INT REFERENCES workers(id),
    process_id INT, -- PID reportado por el Driver
    vnc_port INT,   -- Puerto VNC reportado
    instance_path VARCHAR(255), -- Ruta del disco qcow2 en el Server 4 (NFS/Shared Storage)
    status VARCHAR(20) DEFAULT 'PENDING_APPROVAL',
    vnc_url VARCHAR(500), -- URL VNC para OpenStack
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cada registro representa un enlace lógico (link) de la topología
CREATE TABLE networks (
    id SERIAL PRIMARY KEY,
    slice_id INT REFERENCES slices(id) ON DELETE CASCADE,
    vlan_inner INT NOT NULL, -- Vlan-Inner: etiqueta local dentro del Br-Slice (ej. 100, 200)
    is_remote BOOLEAN DEFAULT FALSE, -- TRUE si las VMs del enlace están en Workers distintos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla asociativa: cada registro es un "cable virtual" que conecta una interfaz de VM al Br-Slice
CREATE TABLE vm_interfaces (
    id SERIAL PRIMARY KEY,
    vm_id INT REFERENCES virtual_machines(id) ON DELETE CASCADE,
    network_id INT REFERENCES networks(id) ON DELETE CASCADE NULL,
    mac_address VARCHAR(17),
    interface_name VARCHAR(20), -- ej. 'eth0', 'eth1' dentro del guest (VM)
    tap_name VARCHAR(30), -- ej. 'tap-vm1-eth0' en el host Worker para OvS
    bridge_name VARCHAR(30)
);

CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    slice_id INT REFERENCES slices(id) ON DELETE CASCADE,
    vm_id INT REFERENCES virtual_machines(id) ON DELETE CASCADE,
    task_type VARCHAR(50) NOT NULL, -- ej. 'CREATE_VM', 'DELETE_VM'
    status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, PLACEMENT_READY, IN_PROGRESS, READY, FAILED
    payload JSONB NOT NULL, -- Datos técnicos para el Driver (reglas firewall, etc)
    worker_id INT REFERENCES workers(id),
    error_msg TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);



-- Tabla de configuración clave-valor para estado persistente de los módulos
-- Ej: el puntero Round Robin del VM Placement ('last_worker_id' -> '2')
CREATE TABLE config (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pre-poblar el pool de VLANs del 100 al 1000
INSERT INTO vlan_pool (vlan_id) SELECT generate_series(100, 1000);

-- Semilla de Workers: solo inventario estático (hostname + IP de gestión).
-- El módulo de Monitoring descubrirá total_ram, total_cpu vía SSH
-- y actualizará periódicamente current_cpu_load, current_ram_available y status.
INSERT INTO workers (hostname, ip_management, total_ram, total_cpu, current_ram_available, cluster_type)
VALUES
    ('server1', '192.168.201.1', 8192, 8, 8192, 'linux'),
    ('server2', '192.168.201.2', 8192, 8, 8192, 'linux'),
    ('server3', '192.168.201.3', 8192, 8, 8192, 'linux'),
    ('worker1', '192.168.202.2', 8192, 8, 8192, 'openstack'),
    ('worker2', '192.168.202.3', 8192, 8, 8192, 'openstack'),
    ('worker3', '192.168.202.4', 8192, 8, 8192, 'openstack');

-- Puntero inicial de Round Robin
INSERT INTO config (key, value) VALUES ('last_worker_id', '0');
