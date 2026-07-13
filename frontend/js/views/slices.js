// ── Vistas de Slices: listar, detalle, aprobar/rechazar, eliminar ──
// Endpoints reales del Slice Manager:
//   GET  /slices/            → {slices:[{id,name,status,iaas_target,vms_count,created_at}]}
//   GET  /slices/{id}        → {id,name,status,vlan_slice,vms:[{...,vnc_url,interfaces}]}
//   GET  /slices/{id}/export → SliceCreate (name,iaas_target,vms,links,networks) — SLICE_ADMIN/SYSTEM_ADMIN
//   PUT  /slices/{id}          (SLICE_ADMIN/SYSTEM_ADMIN) — edita un Borrador (solo DRAFT)
//   POST /slices/{id}/deploy   (SLICE_ADMIN/SYSTEM_ADMIN) — DRAFT -> ACTIVE
//   POST /slices/{id}/approve  (SLICE_ADMIN)
//   POST /slices/{id}/reject   (SLICE_ADMIN)
//   DELETE /slices/{id}

// ── STUDENT: mis slices ───────────────────────────────────────
async function renderMySlices() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const { slices } = await api('GET', '/slices/');
    if (isStale(seq)) return;
    if (slices.length === 0) {
      content.innerHTML = `<div class="card"><div class="empty-state"><div class="empty-icon">🗂️</div><p>No tienes slices. <a href="#" onclick="navigate('new-slice')">Solicita uno.</a></p></div></div>`;
      return;
    }
    content.innerHTML = `<div class="card">
      <div class="card-title">Mis Slices <button class="btn btn-primary btn-sm" onclick="navigate('new-slice')">+ Solicitar Slice</button></div>
      <div class="table-wrap"><table>
        <thead><tr><th>ID</th><th>Nombre</th><th>VMs</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>${slices.map(s => `
          <tr>
            <td class="text-muted">#${s.id}</td>
            <td><strong>${esc(s.name)}</strong></td>
            <td class="text-muted">${s.vms_count}</td>
            <td>${badge(s.status)}</td>
            <td style="display:flex;gap:6px;flex-wrap:wrap">
              <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver detalle</button>
              <button class="btn btn-danger btn-sm" onclick="deleteSlice(${s.id})">Eliminar</button>
            </td>
          </tr>`).join('')}
        </tbody>
      </table></div>
    </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}

// ── SLICE_ADMIN: pendientes de aprobación ─────────────────────
async function renderPending() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const { slices } = await api('GET', '/slices/');
    if (isStale(seq)) return;
    const pending = slices.filter(s => s.status === 'PENDING_APPROVAL');

    if (pending.length === 0) {
      content.innerHTML = `<div class="card"><div class="empty-state"><div class="empty-icon">✅</div><p>No hay solicitudes pendientes.</p></div></div>`;
      return;
    }

    content.innerHTML = `<div class="card">
      <div class="card-title">Solicitudes pendientes de aprobación</div>
      <div class="table-wrap"><table>
        <thead><tr><th>ID</th><th>Nombre</th><th>VMs</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>${pending.map(s => `
          <tr>
            <td class="text-muted">#${s.id}</td>
            <td><strong>${esc(s.name)}</strong></td>
            <td class="text-muted">${s.vms_count}</td>
            <td>${badge(s.status)}</td>
            <td style="display:flex;gap:6px;flex-wrap:wrap">
              <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver</button>
              <button class="btn btn-success btn-sm" onclick="approveSlice(${s.id})">Aprobar</button>
              <button class="btn btn-danger btn-sm"  onclick="rejectSlice(${s.id})">Rechazar</button>
            </td>
          </tr>`).join('')}
        </tbody>
      </table></div>
    </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}

// ── ADMIN: todos los slices ───────────────────────────────────
async function renderAllSlices() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const { slices } = await api('GET', '/slices/');
    if (isStale(seq)) return;

    const draftActions = s => s.status === 'DRAFT'
      ? `<button class="btn btn-ghost btn-sm" onclick="editSlice(${s.id})">Editar</button>
         <button class="btn btn-ghost btn-sm" onclick="exportSlice(${s.id})">Exportar</button>
         <button class="btn btn-success btn-sm" onclick="deploySlice(${s.id})">Desplegar</button>`
      : `<button class="btn btn-ghost btn-sm" onclick="exportSlice(${s.id})">Exportar</button>`;

    const actions = state.user.role === 'SLICE_ADMIN'
      ? s => `
          <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver</button>
          ${s.status === 'PENDING_APPROVAL'
            ? `<button class="btn btn-success btn-sm" onclick="approveSlice(${s.id})">Aprobar</button>
               <button class="btn btn-danger  btn-sm" onclick="rejectSlice(${s.id})">Rechazar</button>`
            : draftActions(s)}
          <button class="btn btn-danger btn-sm" onclick="deleteSlice(${s.id})">Eliminar</button>`
      : s => `
          <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver</button>
          <button class="btn btn-ghost  btn-sm" onclick="viewNetDetail(${s.id})">Red</button>
          ${draftActions(s)}
          <button class="btn btn-danger btn-sm" onclick="deleteSlice(${s.id})">Eliminar</button>`;

    const importBar = `
      <input type="file" id="import-file-input" accept=".json,application/json" style="display:none" onchange="handleImportFile(this)" />
      <button class="btn btn-ghost btn-sm" onclick="document.getElementById('import-file-input').click()">Importar Topología</button>`;

    content.innerHTML = slices.length === 0
      ? `<div class="card">
          <div class="card-title">Todos los Slices ${importBar}</div>
          <div class="empty-state"><div class="empty-icon">📭</div><p>No hay slices en el sistema.</p></div>
        </div>`
      : `<div class="card">
          <div class="card-title" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <span>Todos los Slices</span>${importBar}
          </div>
          <div class="table-wrap"><table>
            <thead><tr><th>ID</th><th>Nombre</th><th>Estado</th><th>VMs</th><th>Creado</th><th>Acciones</th></tr></thead>
            <tbody>${slices.map(s => `
              <tr>
                <td class="text-muted">#${s.id}</td>
                <td><strong>${esc(s.name)}</strong></td>
                <td>${badge(s.status)}</td>
                <td class="text-muted">${s.vms_count}</td>
                <td class="text-muted text-sm">${s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
                <td style="display:flex;gap:6px;flex-wrap:wrap">${actions(s)}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>
        </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}

// ── Detalle de slice (modal) ──────────────────────────────────
// El backend ya no devuelve topología ni IPs en el detalle;
// las interfaces traen: interface_name, tap_name, vlan_inner, bridge_name.
async function viewSliceDetail(id) {
  try {
    const s = await api('GET', `/slices/${id}`);
    const vmsHTML = s.vms.map(vm => `
      <div style="margin-bottom:12px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:6px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <strong style="font-size:13px">${esc(vm.name)}</strong>
          ${badge(vm.status)}
        </div>
        <div style="font-size:12px;color:var(--text-muted);display:flex;gap:16px;margin-bottom:8px;flex-wrap:wrap">
          ${vm.worker_id  ? `<span>Worker: ${vm.worker_id}</span>`   : ''}
          ${vm.vnc_port   ? `<span>VNC: ${vm.vnc_port}</span>`       : ''}
          ${vm.process_id ? `<span>PID: ${vm.process_id}</span>`     : ''}
          ${vm.vnc_url    ? `<a href="${esc(vm.vnc_url)}" target="_blank" rel="noopener" style="color:var(--primary)">Abrir consola VNC ↗</a>` : ''}
        </div>
        ${vm.interfaces.length ? `
          <div class="table-wrap"><table>
            <thead><tr><th>Interfaz</th><th>TAP</th><th>VLAN inner</th><th>Bridge</th></tr></thead>
            <tbody>${vm.interfaces.map(i => `
              <tr>
                <td class="mono">${esc(i.interface_name) || '—'}</td>
                <td class="mono text-muted">${esc(i.tap_name) || '—'}</td>
                <td class="mono text-muted">${i.vlan_inner != null ? i.vlan_inner : '—'}</td>
                <td class="mono text-muted">${esc(i.bridge_name) || '—'}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>` : '<p class="text-muted text-sm">Sin interfaces asignadas aún.</p>'}
      </div>`).join('') || '<p class="text-muted text-sm">No hay VMs.</p>';

    openModal(`Slice #${s.id} — ${esc(s.name)}`, `
      <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
        ${badge(s.status)}
        <span class="text-muted text-sm">ID: ${s.id}</span>
        ${s.vlan_slice ? `<span class="text-muted text-sm">VLAN-Slice: ${s.vlan_slice}</span>` : ''}
      </div>
      <div class="card-title" style="margin-bottom:12px">Máquinas Virtuales</div>
      ${vmsHTML}
    `);
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Acciones ──────────────────────────────────────────────────
async function approveSlice(id) {
  try {
    const res = await api('POST', `/slices/${id}/approve`);
    toast(res.message || `Slice #${id} aprobado`, 'success');
    navigate(state.view);
  } catch (e) { toast(e.message, 'error'); }
}

async function rejectSlice(id) {
  if (!confirm(`¿Rechazar slice #${id}?`)) return;
  try {
    await api('POST', `/slices/${id}/reject`);
    toast(`Slice #${id} rechazado`, 'info');
    navigate(state.view);
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteSlice(id) {
  if (!confirm(`¿Eliminar slice #${id}? Se apagarán sus VMs y se liberará la red.`)) return;
  try {
    await api('DELETE', `/slices/${id}`);
    toast('Slice eliminado', 'success');
    navigate(state.view);
  } catch (e) {
    toast(e.message, 'error');
  }
}

// Abre el diseñador de topologías (designer.js) precargado con un Borrador
// existente, para editarlo antes de desplegarlo.
async function editSlice(id) {
  try {
    const data = await api('GET', `/slices/${id}/export`);
    state.view = 'new-slice';
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.view === 'new-slice');
    });
    document.getElementById('topbar-title').textContent = 'Editar Slice';
    renderNewSlice(id, data);
  } catch (e) { toast(e.message, 'error'); }
}

async function deploySlice(id) {
  if (!confirm(`¿Desplegar slice #${id}? Se creará la infraestructura real (VMs + red).`)) return;
  try {
    const res = await api('POST', `/slices/${id}/deploy`);
    toast(res.message || `Slice #${id} desplegado`, 'success');
    navigate(state.view);
  } catch (e) { toast(e.message, 'error'); }
}

// ── Exportar / Importar topología (Borradores) ─────────────────
async function exportSlice(id) {
  try {
    const data = await api('GET', `/slices/${id}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.name || 'slice'}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast(e.message, 'error');
  }
}

let _importedTopology = null;

async function handleImportFile(input) {
  const file = input.files[0];
  input.value = '';
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    if (!Array.isArray(parsed.vms) || !parsed.vms.length) throw new Error('El archivo no contiene VMs (vms[])');
    if (!Array.isArray(parsed.links)) throw new Error('El archivo no contiene enlaces (links[])');
    _importedTopology = parsed;

    openModal('Importar Topología', `
      <p class="text-muted text-sm" style="margin-bottom:12px">
        ${parsed.vms.length} VM(s), ${parsed.links.length} enlace(s) — destino: ${esc(parsed.iaas_target || 'linux')}
      </p>
      <div class="field">
        <label>Nombre del nuevo Slice</label>
        <input type="text" id="import-new-name" value="${esc((parsed.name || 'topologia') + '_import')}" />
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
        <button class="btn btn-ghost btn-sm" onclick="closeModal()">Cancelar</button>
        <button class="btn btn-primary btn-sm" onclick="confirmImport()">Importar como Borrador</button>
      </div>
    `);
  } catch (e) {
    toast(`Archivo inválido: ${e.message}`, 'error');
  }
}

async function confirmImport() {
  const name = document.getElementById('import-new-name')?.value?.trim();
  if (!name) { toast('Ingresa un nombre', 'error'); return; }
  if (!_importedTopology) return;
  try {
    const payload = { ..._importedTopology, name };
    await api('POST', '/slices/', payload);
    closeModal();
    _importedTopology = null;
    toast('Topología importada como nuevo Borrador', 'success');
    navigate(state.view);
  } catch (e) {
    toast(e.message, 'error');
  }
}
