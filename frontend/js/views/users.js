// ── Gestión de usuarios ───────────────────────────────────────
// El servicio Auth solo expone: register, login, verify.
// No hay endpoint para listar usuarios, así que la vista es solo de registro.
//   - SLICE_ADMIN crea STUDENTs asignados a sí mismo
//   - SYSTEM_ADMIN crea cualquier rol (STUDENT requiere el ID de su SLICE_ADMIN)

function renderUsers() {
  beginRender(); // invalida fetches pendientes de la vista anterior
  const content = document.getElementById('content');
  const isSysAdmin = state.user.role === 'SYSTEM_ADMIN';

  content.innerHTML = `
    <div class="card">
      <div class="card-title">Registrar usuario</div>
      <p class="text-muted text-sm" style="margin:-4px 0 12px">
        ${isSysAdmin
          ? 'Para crear un STUDENT necesitas el ID del SLICE_ADMIN responsable.'
          : 'Los estudiantes que registres quedarán asignados a tu cuenta.'}
      </p>
      <div class="field"><label>Username</label><input type="text" id="nu-username" autocomplete="off" /></div>
      <div class="field"><label>Contraseña</label><input type="password" id="nu-password" autocomplete="new-password" /></div>
      <div class="field"><label>Rol</label>
        <select id="nu-role" onchange="nuToggleAdmin(this.value)">
          <option value="STUDENT">STUDENT</option>
          ${isSysAdmin ? `
            <option value="SLICE_ADMIN">SLICE_ADMIN</option>
            <option value="SYSTEM_ADMIN">SYSTEM_ADMIN</option>` : ''}
        </select>
      </div>
      ${isSysAdmin
        ? `<div class="field" id="nu-admin-field">
            <label>ID del Slice Admin responsable</label>
            <input type="number" id="nu-admin-id" min="1" placeholder="ej. 2" />
           </div>`
        : `<input type="hidden" id="nu-admin-id" value="${state.user.id}" />`}
      <button class="btn btn-primary" onclick="createUser()">Crear usuario</button>
    </div>`;
}

function nuToggleAdmin(role) {
  const field = document.getElementById('nu-admin-field');
  if (field) field.style.display = role === 'STUDENT' ? '' : 'none';
}

async function createUser() {
  const username  = document.getElementById('nu-username')?.value?.trim();
  const password  = document.getElementById('nu-password')?.value;
  const role      = document.getElementById('nu-role')?.value;
  const adminIdEl = document.getElementById('nu-admin-id');
  const admin_id  = adminIdEl ? parseInt(adminIdEl.value, 10) || null : null;

  if (!username || !password) { toast('Username y contraseña son requeridos', 'error'); return; }
  if (role === 'STUDENT' && !admin_id) { toast('Indica el ID del Slice Admin responsable', 'error'); return; }
  try {
    const body = { username, password, role };
    if (role === 'STUDENT') body.admin_id = admin_id;
    const created = await api('POST', '/auth/register', body);
    toast(`Usuario "${username}" creado (ID ${created.id})`, 'success');
    renderUsers();
  } catch (e) { toast(e.message, 'error'); }
}
