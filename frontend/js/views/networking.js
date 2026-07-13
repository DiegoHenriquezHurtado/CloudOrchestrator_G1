// ── Redes & VLANs (SYSTEM_ADMIN) ──────────────────────────────
// GET /networking/vlans/available       → {total, available, used}
// GET /networking/networks/{slice_id}   → plan de red del slice
// GET /networking/ovs/commands/{slice_id} → comandos OvS por worker

async function renderNetworking() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;

  try {
    const [slicesData, vlans] = await Promise.all([
      api('GET', '/slices/'),
      api('GET', '/networking/vlans/available'),
    ]);
    if (isStale(seq)) return;
    const slices = slicesData.slices;
    const withNet = slices.filter(s => s.status === 'ACTIVE');

    content.innerHTML = `
      <div class="grid-stats" style="margin-bottom:20px">
        <div class="stat-card">
          <div class="stat-value" style="color:var(--purple)">${vlans.available}</div>
          <div class="stat-label">VLANs disponibles (pool 100–1000)</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${vlans.used}</div>
          <div class="stat-label">VLANs en uso</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${vlans.total}</div>
          <div class="stat-label">Total del pool</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Slices activos</div>
        <p class="text-muted text-sm" style="margin:-4px 0 10px">
          El plan de red y los comandos OvS aplican a slices del cluster Linux.
        </p>
        ${withNet.length === 0
          ? '<div class="empty-state"><div class="empty-icon">🔌</div><p>No hay slices activos.</p></div>'
          : `<div class="table-wrap"><table>
              <thead><tr><th>Slice</th><th>Estado</th><th>Acciones</th></tr></thead>
              <tbody>${withNet.map(s => `
                <tr>
                  <td><strong>#${s.id}</strong> — ${esc(s.name)}</td>
                  <td>${badge(s.status)}</td>
                  <td style="display:flex;gap:6px">
                    <button class="btn btn-ghost btn-sm" onclick="viewNetDetail(${s.id})">Ver plan de red</button>
                    <button class="btn btn-ghost btn-sm" onclick="viewOvsCommands(${s.id})">Comandos OvS</button>
                  </td>
                </tr>`).join('')}
              </tbody>
            </table></div>`}
      </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}

async function viewNetDetail(sliceId) {
  try {
    const net = await api('GET', `/networking/networks/${sliceId}`);
    if (!net.networks.length) {
      openModal(`Red del Slice #${sliceId}`, '<p class="text-muted text-sm">Este slice no tiene redes registradas (posiblemente es un slice de OpenStack).</p>');
      return;
    }
    const rows = net.networks.map(n => `
      <div class="net-plan-row">
        <span class="tag tag-inner">VI:${n.vlan_inner}</span>
        <span class="tag ${n.is_remote ? 'tag-remote' : 'tag-local'}">${n.is_remote ? 'REMOTO' : 'LOCAL'}</span>
        <span class="mono" style="flex:1">${n.id != null ? `red #${n.id}` : 'br-inet (Internet)'}</span>
        <span class="text-muted text-xs">${n.is_remote ? '🔀' : '🔗'}</span>
      </div>
      <div style="padding:0 12px 10px">
        ${n.interfaces.map(i => `
          <div style="display:flex;gap:12px;font-size:11px;color:var(--text-muted);padding:3px 0;flex-wrap:wrap">
            <span class="mono">${esc(i.tap_name)}</span>
            <span class="mono" style="color:var(--text-dim)">${esc(i.mac_address)}</span>
            <span class="mono">${esc(i.bridge_name)}</span>
            <span>VM${i.vm_id}${i.worker_id != null ? ` @ W${i.worker_id}` : ''}</span>
          </div>`).join('')}
      </div>`).join('');

    openModal(`Red del Slice #${sliceId} — Vlan-Slice: ${net.vlan_slice} / Bridge: ${esc(net.bridge_name)}`, `
      <div style="margin-bottom:12px;font-size:12px;color:var(--text-muted)">
        <span class="tag tag-inner">VI = Vlan-Inner (local al Br-Slice)</span>
        <span class="tag tag-slice">Vlan-Slice ${net.vlan_slice} = transporte inter-worker</span>
      </div>
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;overflow:hidden">
        ${rows}
      </div>`);
  } catch (e) { toast(e.message, 'error'); }
}

async function viewOvsCommands(sliceId) {
  try {
    const ovs = await api('GET', `/networking/ovs/commands/${sliceId}`);
    const workersHTML = ovs.workers.length === 0
      ? '<p class="text-muted text-sm">No hay comandos generados para este slice.</p>'
      : ovs.workers.map(w => `
        <div class="worker-block">
          <div class="worker-block-title">Worker ${w.worker_id}</div>
          <div class="code-block"><pre>${esc(w.commands.join('\n'))}</pre></div>
        </div>`).join('');

    openModal(`Comandos OvS — Slice #${sliceId} (Vlan-Slice: ${ovs.vlan_slice})`, workersHTML);
  } catch (e) { toast(e.message, 'error'); }
}
