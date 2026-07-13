// ── Dashboard (todos los roles) ───────────────────────────────

async function renderOverview() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="grid-stats" id="stats-grid"><div class="text-muted">Cargando...</div></div>`;

  try {
    const { slices } = await api('GET', '/slices/');
    if (isStale(seq)) return;

    const total   = slices.length;
    const active  = slices.filter(s => s.status === 'ACTIVE').length;
    const pending = slices.filter(s => s.status.includes('PENDING')).length;

    let statsHTML = `
      <div class="stat-card"><div class="stat-value">${total}</div><div class="stat-label">Slices totales</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--success)">${active}</div><div class="stat-label">Activos</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--warning)">${pending}</div><div class="stat-label">Pendientes</div></div>
    `;

    // Solo SYSTEM_ADMIN puede consultar networking (ROLE_RULES del gateway)
    if (state.user.role === 'SYSTEM_ADMIN') {
      try {
        const vlans = await api('GET', '/networking/vlans/available');
        statsHTML += `<div class="stat-card"><div class="stat-value" style="color:var(--purple)">${vlans.available}</div><div class="stat-label">VLANs disponibles</div></div>`;
      } catch { /* networking caído: no bloquear el dashboard */ }
      if (isStale(seq)) return;
    }

    content.innerHTML = `
      <div class="grid-stats">${statsHTML}</div>
      <div class="card">
        <div class="card-title">Actividad reciente</div>
        ${slices.length === 0 ? '<div class="empty-state"><div class="empty-icon">📭</div><p>No hay slices aún.</p></div>' :
          `<div class="table-wrap"><table>
            <thead><tr><th>ID</th><th>Nombre</th><th>VMs</th><th>Estado</th><th>Creado</th></tr></thead>
            <tbody>${slices.slice(0, 8).map(s => `
              <tr>
                <td class="text-muted">#${s.id}</td>
                <td><strong>${esc(s.name)}</strong></td>
                <td class="text-muted">${s.vms_count}</td>
                <td>${badge(s.status)}</td>
                <td class="text-muted text-sm">${s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>`}
      </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}
