// ── Infraestructura (SYSTEM_ADMIN): workers ───────────────────
// GET /infra/workers      → Monitoring: hostname, ip_management, total_ram,
//                           total_cpu, current_cpu_load, current_ram_available,
//                           status, updated_at

async function renderInfra() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const data = await api('GET', '/infra/workers');
    if (isStale(seq)) return;
    const workers = data.workers || [];
    const alive = workers.filter(w => w.status === 'ALIVE').length;
    const down  = workers.filter(w => w.status === 'DOWN').length;

    content.innerHTML = `
      <div class="grid-stats" style="margin-bottom:20px">
        <div class="stat-card"><div class="stat-value">${workers.length}</div><div class="stat-label">Workers totales</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--success)">${alive}</div><div class="stat-label">ALIVE</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--danger)">${down}</div><div class="stat-label">DOWN</div></div>
      </div>
      <div class="card">
        <div class="card-title">Estado de Workers</div>
        ${workers.length === 0
          ? '<div class="empty-state"><div class="empty-icon">🖥️</div><p>No hay workers registrados.</p></div>'
          : `<div class="table-wrap"><table>
              <thead><tr><th>ID</th><th>Hostname</th><th>IP Mgmt</th><th>CPU cores</th><th>CPU load</th><th>RAM total</th><th>RAM disp.</th><th>Estado</th><th>Última actualización</th></tr></thead>
              <tbody>${workers.map(w => `
                <tr>
                  <td class="text-muted">#${w.id}</td>
                  <td><strong>${esc(w.hostname) || '—'}</strong></td>
                  <td class="mono">${esc(w.ip_management) || '—'}</td>
                  <td class="mono">${w.total_cpu ?? '—'}</td>
                  <td class="mono">${w.current_cpu_load != null ? Number(w.current_cpu_load).toFixed(2) + '%' : '—'}</td>
                  <td class="mono">${w.total_ram != null ? w.total_ram + ' MB' : '—'}</td>
                  <td class="mono">${w.current_ram_available != null ? w.current_ram_available + ' MB' : '—'}</td>
                  <td>${badge(w.status)}</td>
                  <td class="text-muted text-sm">${w.updated_at ? new Date(w.updated_at).toLocaleString() : '—'}</td>
                </tr>`).join('')}
              </tbody>
            </table></div>`}
      </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}
