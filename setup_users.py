#!/usr/bin/env python3
"""
Crea los usuarios de prueba para el frontend via la API de Auth.

Uso:
  python setup_users.py
  python setup_users.py http://localhost:8080  # si el gateway está en otro host

Usuarios que crea (contraseña: admin123 para todos):
  admin        → SYSTEM_ADMIN
  slice_admin  → SLICE_ADMIN
  student1     → STUDENT (asignado a slice_admin)
"""

import json, sys, urllib.request, urllib.error

BASE = (sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://localhost:8080') + '/api/v1'


def post(path, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(f"{BASE}{path}", data=data,
                                  headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read()).get('detail', str(e))


def register(username, password, role, admin_id=None):
    body = {'username': username, 'password': password, 'role': role}
    if admin_id:
        body['admin_id'] = admin_id
    resp, err = post('/auth/register', body)
    if err:
        print(f"  [{username}] Ya existe o error: {err}")
    else:
        print(f"  [{username}] Creado → id={resp['id']}  role={resp['role']}")
    return resp


print("Registrando usuarios de prueba...")

admin = register('admin',       'admin123', 'SYSTEM_ADMIN')
sadmin = register('slice_admin', 'admin123', 'SLICE_ADMIN')

sadmin_id = sadmin['id'] if sadmin else 2
register('student1', 'admin123', 'STUDENT', admin_id=sadmin_id)

print("""
Listo. Credenciales:
  admin        / admin123  →  SYSTEM_ADMIN
  slice_admin  / admin123  →  SLICE_ADMIN
  student1     / admin123  →  STUDENT
""")
