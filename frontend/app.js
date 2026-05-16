// Cambia esta URL si el gateway corre en otro host/puerto
const API = 'http://localhost:8080/api/v1';

// ── Estado global ─────────────────────────────────────────────
const state = {
  token: localStorage.getItem('co_token') || null,
  user:  JSON.parse(localStorage.getItem('co_user') || 'null'),
  view:  null,
};

// ── API helper ────────────────────────────────────────────────
async function api(method, path, body = null) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;

  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });

  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

// ── Toast ─────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-dot"></span>${msg}`;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Modal ─────────────────────────────────────────────────────
function openModal(title, html) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = html;
  document.getElementById('modal-overlay').classList.remove('hidden');
}
function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  document.getElementById('modal-body').innerHTML = '';
}

// ── Status badge ──────────────────────────────────────────────
function badge(status) {
  const map = {
    ACTIVE:           'badge-active',
    READY:            'badge-active',
    PENDING_APPROVAL: 'badge-pending',
    PENDING:          'badge-pending',
    PLACEMENT_READY:  'badge-pending',
    IN_PROGRESS:      'badge-pending',
    FAILED:           'badge-failed',
    TERMINATING:      'badge-failed',
    REJECTED:         'badge-failed',
    DELETED:          'badge-failed',
  };
  const cls = map[status] || 'badge-info';
  return `<span class="badge ${cls}">${status}</span>`;
}

// ── Auth ──────────────────────────────────────────────────────
async function login(username, password) {
  const data = await api('POST', '/auth/login', { username, password });
  state.token = data.access_token;
  localStorage.setItem('co_token', state.token);

  // Decode payload (no verify — gateway does that)
  const payload = JSON.parse(atob(state.token.split('.')[1]));
  state.user = { id: payload.sub, username: payload.username, role: payload.role };
  localStorage.setItem('co_user', JSON.stringify(state.user));
}

function logout() {
  state.token = null;
  state.user  = null;
  localStorage.removeItem('co_token');
  localStorage.removeItem('co_user');
  showLogin();
}

// ── Sidebar nav config ────────────────────────────────────────
function navItems(role) {
  const icon = {
    dashboard: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
    slices:    `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>`,
    new:       `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>`,
    pending:   `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    network:   `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><line x1="12" y1="8" x2="5.5" y2="16.5"/><line x1="12" y1="8" x2="18.5" y2="16.5"/></svg>`,
    infra:     `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="4" rx="1"/><rect x="2" y="10" width="20" height="4" rx="1"/><rect x="2" y="17" width="20" height="4" rx="1"/></svg>`,
  };

  const all = {
    STUDENT: [
      { id: 'overview',    label: 'Dashboard',       icon: icon.dashboard },
      { id: 'my-slices',   label: 'Mis Slices',       icon: icon.slices   },
      { id: 'new-slice',   label: 'Solicitar Slice',  icon: icon.new      },
    ],
    SLICE_ADMIN: [
      { id: 'overview',    label: 'Dashboard',        icon: icon.dashboard },
      { id: 'pending',     label: 'Pendientes',        icon: icon.pending  },
      { id: 'all-slices',  label: 'Todos los Slices',  icon: icon.slices   },
    ],
    SYSTEM_ADMIN: [
      { id: 'overview',    label: 'Dashboard',         icon: icon.dashboard },
      { id: 'all-slices',  label: 'Todos los Slices',  icon: icon.slices    },
      { id: 'networking',  label: 'Red & Seguridad',   icon: icon.network   },
    ],
  };
  return all[role] || [];
}

// ── Router (show/hide pages) ──────────────────────────────────
function navigate(viewId) {
  state.view = viewId;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === viewId);
  });

  const titles = {
    'overview':   'Dashboard',
    'my-slices':  'Mis Slices',
    'new-slice':  'Solicitar Slice',
    'pending':    'Solicitudes Pendientes',
    'all-slices': 'Todos los Slices',
    'networking': 'Red & Seguridad',
  };
  document.getElementById('topbar-title').textContent = titles[viewId] || viewId;

  const render = {
    'overview':   renderOverview,
    'my-slices':  renderMySlices,
    'new-slice':  renderNewSlice,
    'pending':    renderPending,
    'all-slices': renderAllSlices,
    'networking': renderNetworking,
  };

  const fn = render[viewId];
  if (fn) fn();
}

// ── Shell ─────────────────────────────────────────────────────
function showLogin() {
  document.getElementById('login-page').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function showApp() {
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  const u = state.user;
  document.getElementById('user-avatar').textContent = u.username[0].toUpperCase();
  document.getElementById('user-name').textContent = u.username;

  const rb = document.getElementById('user-role-badge');
  rb.textContent = u.role;
  rb.className = `role-badge ${u.role}`;

  // Build sidebar nav
  const nav = document.getElementById('sidebar-nav');
  nav.innerHTML = navItems(u.role).map(item => `
    <button class="nav-item" data-view="${item.id}" onclick="navigate('${item.id}')">
      ${item.icon}<span>${item.label}</span>
    </button>
  `).join('');

  navigate(navItems(u.role)[0].id);
}

// ── VIEWS ─────────────────────────────────────────────────────

async function renderOverview() {
  const content = document.getElementById('content');
  content.innerHTML = `<div class="grid-stats" id="stats-grid"><div class="text-muted">Cargando...</div></div>`;

  try {
    const { slices } = await api('GET', '/slices/');

    const total    = slices.length;
    const active   = slices.filter(s => s.status === 'ACTIVE').length;
    const pending  = slices.filter(s => s.status.includes('PENDING')).length;

    let statsHTML = `
      <div class="stat-card"><div class="stat-value">${total}</div><div class="stat-label">Slices totales</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--success)">${active}</div><div class="stat-label">Activos</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--warning)">${pending}</div><div class="stat-label">Pendientes</div></div>
    `;

    if (state.user.role === 'SYSTEM_ADMIN') {
      const vlans = await api('GET', '/networking/vlans/available');
      statsHTML += `<div class="stat-card"><div class="stat-value" style="color:var(--purple)">${vlans.available}</div><div class="stat-label">VLANs disponibles</div></div>`;
    }

    content.innerHTML = `
      <div class="grid-stats">${statsHTML}</div>
      <div class="card">
        <div class="card-title">Actividad reciente</div>
        ${slices.length === 0 ? '<div class="empty-state"><div class="empty-icon">📭</div><p>No hay slices aún.</p></div>' :
          `<div class="table-wrap"><table>
            <thead><tr><th>ID</th><th>Nombre</th><th>Estado</th></tr></thead>
            <tbody>${slices.slice(0, 8).map(s => `
              <tr>
                <td class="text-muted">#${s.id}</td>
                <td><strong>${s.name}</strong></td>
                <td>${badge(s.status)}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>`}
      </div>`;
  } catch (e) {
    content.innerHTML = `<div class="card"><p class="error-msg">${e.message}</p></div>`;
  }
}

// ── STUDENT: mis slices ───────────────────────────────────────
async function renderMySlices() {
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const { slices } = await api('GET', '/slices/');
    if (slices.length === 0) {
      content.innerHTML = `<div class="card"><div class="empty-state"><div class="empty-icon">🗂️</div><p>No tienes slices. <a href="#" onclick="navigate('new-slice')">Solicita uno.</a></p></div></div>`;
      return;
    }
    content.innerHTML = `<div class="card">
      <div class="card-title">Mis Slices <button class="btn btn-primary btn-sm" onclick="navigate('new-slice')">+ Solicitar Slice</button></div>
      <div class="table-wrap"><table>
        <thead><tr><th>ID</th><th>Nombre</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>${slices.map(s => `
          <tr>
            <td class="text-muted">#${s.id}</td>
            <td><strong>${s.name}</strong></td>
            <td>${badge(s.status)}</td>
            <td>
              <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver detalle</button>
              <button class="btn btn-danger btn-sm" onclick="deleteSlice(${s.id})">Eliminar</button>
            </td>
          </tr>`).join('')}
        </tbody>
      </table></div>
    </div>`;
  } catch (e) {
    content.innerHTML = `<div class="card"><p class="error-msg">${e.message}</p></div>`;
  }
}

// ── TOPOLOGY DESIGNER ────────────────────────────────────────
// Estado global del diseñador (se reinicia en cada renderNewSlice)
let TD = null;

const TD_LINK_COLORS = [
  '#22c55e','#06b6d4','#f59e0b','#8b5cf6',
  '#ec4899','#ef4444','#38bdf8','#f43f5e',
];
const TD_VM_W = 100, TD_VM_H = 38, TD_VM_R = 8;

function tdLinkColor(idx) { return TD_LINK_COLORS[idx % TD_LINK_COLORS.length]; }

// ── STUDENT: nuevo slice — diseñador visual ───────────────────
function renderNewSlice() {
  if (TD?.animFrame) cancelAnimationFrame(TD.animFrame);

  TD = {
    vms: [], links: [],
    nextVmId: 1, nextLinkId: 1,
    selected: null,   // {type:'vm'|'link', id}
    mode: 'select',
    connectFrom: null,
    drag: null,       // {vmId, ox, oy}
    mouseX: 0, mouseY: 0,
    animFrame: null,
  };

  const content = document.getElementById('content');
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 230px;gap:14px;height:calc(100vh - 110px)">

      <div style="display:flex;flex-direction:column;gap:10px;min-height:0">
        <!-- Toolbar -->
        <div class="card" style="padding:10px 14px;margin:0;flex-shrink:0">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <div class="field" style="margin:0;flex:1;min-width:160px">
              <input type="text" id="td-name" placeholder="Nombre del Slice" style="font-weight:600" />
            </div>
            <div style="display:flex;gap:6px;align-items:center">
              <button class="btn btn-ghost btn-sm" id="btn-td-select" onclick="tdSetMode('select')" title="Seleccionar / mover VMs">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l14 9-7 1-4 7z"/></svg> Mover
              </button>
              <button class="btn btn-ghost btn-sm" id="btn-td-connect" onclick="tdSetMode('connect')" title="Dibujar enlace entre VMs">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg> Enlazar
              </button>
              <div style="width:1px;height:20px;background:var(--border)"></div>
              <button class="btn btn-ghost btn-sm" onclick="tdAddVM()">+ VM</button>
              <button class="btn btn-danger btn-sm" onclick="tdDeleteSelected()">Eliminar</button>
            </div>
            <button class="btn btn-primary" onclick="tdSubmit()">Enviar solicitud</button>
          </div>
        </div>

        <!-- Canvas -->
        <div class="card" style="flex:1;padding:0;margin:0;overflow:hidden;position:relative">
          <canvas id="td-canvas" style="display:block;width:100%;height:100%"></canvas>
          <div id="td-hint" style="position:absolute;bottom:10px;left:50%;transform:translateX(-50%);
               font-size:11px;color:rgba(139,92,246,0.55);pointer-events:none;white-space:nowrap"></div>
        </div>
      </div>

      <!-- Panel derecho -->
      <div style="display:flex;flex-direction:column;gap:10px;overflow-y:auto">
        <div class="card" id="td-props" style="margin:0">
          <div class="card-title">Propiedades</div>
          <p class="text-muted text-sm">Selecciona una VM para editarla.</p>
        </div>
        <div class="card" style="margin:0">
          <div class="card-title" style="margin-bottom:8px">Topología</div>
          <div id="td-summary" style="font-size:12px;color:var(--text-muted)">VMs: 0 | Links: 0</div>
        </div>
        <div class="card" style="margin:0;background:var(--bg);border-color:var(--border)">
          <div style="font-size:11px;color:var(--text-dim);line-height:2">
            <div><b style="color:var(--text-muted)">Mover</b> — arrastra una VM</div>
            <div><b style="color:var(--text-muted)">Enlazar</b> — modo Enlazar, click en 2 VMs</div>
            <div><b style="color:var(--text-muted)">Editar</b> — selecciona una VM</div>
            <div><b style="color:var(--text-muted)">Borrar</b> — selecciona + Eliminar</div>
          </div>
        </div>
      </div>
    </div>`;

  setTimeout(tdInitCanvas, 20);
}

function tdInitCanvas() {
  const canvas = document.getElementById('td-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    canvas.width  = r.width;
    canvas.height = r.height;
  }
  resize();

  const ro = new ResizeObserver(resize);
  ro.observe(canvas.parentElement);

  canvas.addEventListener('mousedown',  e => tdMouseDown(e, canvas));
  canvas.addEventListener('mousemove',  e => tdMouseMove(e, canvas));
  canvas.addEventListener('mouseup',    ()  => { TD.drag = null; });
  canvas.addEventListener('mouseleave', ()  => { TD.drag = null; });

  function loop() {
    tdRender(ctx, canvas.width, canvas.height);
    TD.animFrame = requestAnimationFrame(loop);
  }
  loop();

  // Activate select mode visually
  tdSetMode('select');
}

function tdCanvasPos(e, canvas) {
  const r = canvas.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

function tdVmAt(x, y) {
  return TD.vms.find(v =>
    x >= v.x - TD_VM_W/2 && x <= v.x + TD_VM_W/2 &&
    y >= v.y - TD_VM_H/2 && y <= v.y + TD_VM_H/2
  );
}

function tdLinkEndpoints(link) {
  const a = TD.vms.find(v => v.id === link.vmA);
  const b = TD.vms.find(v => v.id === link.vmB);
  if (!a || !b) return { x1:0, y1:0, x2:0, y2:0 };
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.max(1, Math.hypot(dx, dy));
  const ex = dx/len, ey = dy/len;
  return {
    x1: a.x + ex * TD_VM_W/2, y1: a.y + ey * TD_VM_H/2,
    x2: b.x - ex * TD_VM_W/2, y2: b.y - ey * TD_VM_H/2,
  };
}

function tdLinkAt(x, y) {
  return TD.links.find(l => {
    const {x1,y1,x2,y2} = tdLinkEndpoints(l);
    const dx=x2-x1, dy=y2-y1, lenSq=dx*dx+dy*dy;
    if (lenSq===0) return false;
    const t = Math.max(0,Math.min(1,((x-x1)*dx+(y-y1)*dy)/lenSq));
    return Math.hypot(x-(x1+t*dx), y-(y1+t*dy)) < 9;
  });
}

function tdMouseDown(e, canvas) {
  const {x, y} = tdCanvasPos(e, canvas);
  const vm = tdVmAt(x, y);

  if (TD.mode === 'connect') {
    if (!vm) return;
    if (!TD.connectFrom) {
      TD.connectFrom = vm.id;
      tdSetHint('Ahora haz click en la VM de destino');
    } else if (TD.connectFrom !== vm.id) {
      // evitar duplicado
      const dup = TD.links.some(l =>
        (l.vmA===TD.connectFrom&&l.vmB===vm.id)||(l.vmA===vm.id&&l.vmB===TD.connectFrom));
      if (!dup) {
        const id = TD.nextLinkId++;
        TD.links.push({ id, name:`link-${id}`, vmA:TD.connectFrom, vmB:vm.id });
        TD.selected = { type:'link', id };
        tdRenderProps();
        tdUpdateSummary();
      }
      TD.connectFrom = null;
      tdSetHint('Enlace creado. Haz click en otra VM de origen o cambia de modo.');
    }
    return;
  }

  // Select mode
  if (vm) {
    TD.selected = { type:'vm', id:vm.id };
    TD.drag = { vmId:vm.id, ox:x-vm.x, oy:y-vm.y };
    tdRenderProps();
  } else {
    const link = tdLinkAt(x, y);
    TD.selected = link ? { type:'link', id:link.id } : null;
    tdRenderProps();
  }
}

function tdMouseMove(e, canvas) {
  const {x, y} = tdCanvasPos(e, canvas);
  TD.mouseX = x; TD.mouseY = y;
  if (TD.drag) {
    const vm = TD.vms.find(v => v.id === TD.drag.vmId);
    if (vm) { vm.x = x - TD.drag.ox; vm.y = y - TD.drag.oy; }
  }
  const onVm = !!tdVmAt(x, y);
  canvas.style.cursor = TD.drag ? 'grabbing' : (onVm ? 'grab' : 'default');
}

// ── Canvas render ─────────────────────────────────────────────
function tdRrect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y);
  ctx.quadraticCurveTo(x+w,y,x+w,y+r); ctx.lineTo(x+w,y+h-r);
  ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h); ctx.lineTo(x+r,y+h);
  ctx.quadraticCurveTo(x,y+h,x,y+h-r); ctx.lineTo(x,y+r);
  ctx.quadraticCurveTo(x,y,x+r,y); ctx.closePath();
}

function tdRender(ctx, W, H) {
  ctx.clearRect(0,0,W,H);

  // Background gradient + dot grid
  const g = ctx.createRadialGradient(W/2,H/3,0, W/2,H/2,Math.max(W,H));
  g.addColorStop(0,'#0d1525'); g.addColorStop(1,'#060a12');
  ctx.fillStyle = g; ctx.fillRect(0,0,W,H);
  ctx.fillStyle = 'rgba(100,116,139,0.055)';
  for (let gx=20;gx<W;gx+=30) for (let gy=20;gy<H;gy+=30) {
    ctx.beginPath(); ctx.arc(gx,gy,0.65,0,Math.PI*2); ctx.fill();
  }

  // Links
  TD.links.forEach((link, i) => {
    const {x1,y1,x2,y2} = tdLinkEndpoints(link);
    const color = tdLinkColor(i);
    const sel = TD.selected?.type==='link' && TD.selected?.id===link.id;
    ctx.save();
    ctx.shadowColor = color; ctx.shadowBlur = sel ? 16 : 7;
    ctx.strokeStyle = color; ctx.lineWidth = sel ? 2.5 : 1.8;
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
    ctx.shadowBlur = 0;

    // Link label
    const mx=(x1+x2)/2, my=(y1+y2)/2;
    const dx=x2-x1, dy=y2-y1, len=Math.max(1,Math.hypot(dx,dy));
    const nx=-dy/len, ny=dx/len;
    const lx=mx+nx*15, ly=my+ny*15;
    ctx.font='600 9px "SFMono-Regular",Consolas,monospace';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    const tw=ctx.measureText(link.name).width+10;
    ctx.fillStyle='rgba(6,10,18,0.88)';
    tdRrect(ctx,lx-tw/2,ly-7,tw,14,3); ctx.fill();
    ctx.strokeStyle=color; ctx.lineWidth=0.6;
    tdRrect(ctx,lx-tw/2,ly-7,tw,14,3); ctx.stroke();
    ctx.fillStyle=color; ctx.fillText(link.name,lx,ly);
    ctx.restore();
  });

  // Dashed line from connectFrom to mouse
  if (TD.mode==='connect' && TD.connectFrom) {
    const vm = TD.vms.find(v=>v.id===TD.connectFrom);
    if (vm) {
      ctx.save();
      ctx.setLineDash([5,4]); ctx.strokeStyle='rgba(139,92,246,0.5)'; ctx.lineWidth=1.5;
      ctx.beginPath(); ctx.moveTo(vm.x,vm.y); ctx.lineTo(TD.mouseX,TD.mouseY); ctx.stroke();
      ctx.restore();
    }
  }

  // VMs
  TD.vms.forEach(vm => {
    const x=vm.x-TD_VM_W/2, y=vm.y-TD_VM_H/2;
    const sel  = TD.selected?.type==='vm' && TD.selected?.id===vm.id;
    const src  = TD.connectFrom===vm.id;
    ctx.save();
    ctx.shadowColor = src ? 'rgba(139,92,246,0.7)' : 'rgba(139,92,246,0.28)';
    ctx.shadowBlur  = sel||src ? 22 : 9;
    ctx.fillStyle   = sel ? 'rgba(139,92,246,0.16)' : '#12081e';
    ctx.strokeStyle = sel||src ? '#a78bfa' : 'rgba(139,92,246,0.55)';
    ctx.lineWidth   = sel||src ? 2 : 1.2;
    tdRrect(ctx,x,y,TD_VM_W,TD_VM_H,TD_VM_R); ctx.fill(); ctx.stroke();
    ctx.font='600 12px "SFMono-Regular",Consolas,monospace';
    ctx.fillStyle = sel ? '#c4b5fd' : '#a78bfacc';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText(vm.name, vm.x, vm.y);
    ctx.restore();
  });

  // Empty state
  if (TD.vms.length===0) {
    ctx.save();
    ctx.font='14px sans-serif'; ctx.fillStyle='rgba(139,92,246,0.22)';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText('Haz click en "+ VM" para agregar máquinas virtuales', W/2, H/2);
    ctx.restore();
  }
}

// ── Designer actions ──────────────────────────────────────────
function tdAddVM() {
  const canvas = document.getElementById('td-canvas');
  const W = canvas?.width || 600, H = canvas?.height || 400;
  const id = TD.nextVmId++;
  TD.vms.push({
    id, name:`VM${id}`,
    base_image:'ubuntu-22.04.qcow2', ram:1024, vcpu:1,
    x: 80 + Math.random()*(W-160),
    y: 60 + Math.random()*(H-120),
  });
  TD.selected = { type:'vm', id };
  tdRenderProps(); tdUpdateSummary();
}

function tdDeleteSelected() {
  if (!TD.selected) return;
  if (TD.selected.type==='vm') {
    const id = TD.selected.id;
    TD.vms   = TD.vms.filter(v=>v.id!==id);
    TD.links = TD.links.filter(l=>l.vmA!==id && l.vmB!==id);
  } else {
    TD.links = TD.links.filter(l=>l.id!==TD.selected.id);
  }
  TD.selected = null;
  tdRenderProps(); tdUpdateSummary();
}

function tdSetMode(mode) {
  TD.mode = mode; TD.connectFrom = null;
  document.getElementById('btn-td-select' )?.classList.toggle('active', mode==='select');
  document.getElementById('btn-td-connect')?.classList.toggle('active', mode==='connect');
  tdSetHint(mode==='connect' ? 'Haz click en la VM de origen del enlace' : '');
}

function tdSetHint(msg) {
  const el = document.getElementById('td-hint');
  if (el) el.textContent = msg;
}

function tdRenderProps() {
  const panel = document.getElementById('td-props');
  if (!panel) return;
  const s = TD.selected;
  if (s?.type==='vm') {
    const vm = TD.vms.find(v=>v.id===s.id);
    if (!vm) return;
    panel.innerHTML = `
      <div class="card-title">${vm.name}</div>
      <div class="field"><label>Nombre</label>
        <input type="text" value="${vm.name}" oninput="tdUpdateVm(${vm.id},'name',this.value)" /></div>
      <div class="field"><label>Imagen base</label>
        <input type="text" value="${vm.base_image}" oninput="tdUpdateVm(${vm.id},'base_image',this.value)" /></div>
      <div class="field-row">
        <div class="field"><label>RAM (MB)</label>
          <input type="number" value="${vm.ram}" min="512" oninput="tdUpdateVm(${vm.id},'ram',+this.value)" /></div>
        <div class="field"><label>vCPUs</label>
          <input type="number" value="${vm.vcpu}" min="1" oninput="tdUpdateVm(${vm.id},'vcpu',+this.value)" /></div>
      </div>`;
  } else if (s?.type==='link') {
    const link = TD.links.find(l=>l.id===s.id);
    if (!link) return;
    const vA = TD.vms.find(v=>v.id===link.vmA)?.name||'?';
    const vB = TD.vms.find(v=>v.id===link.vmB)?.name||'?';
    panel.innerHTML = `
      <div class="card-title">Enlace</div>
      <div class="field"><label>Nombre de la red</label>
        <input type="text" value="${link.name}" oninput="tdUpdateLink(${link.id},'name',this.value)" /></div>
      <p class="text-muted text-sm" style="margin-top:6px">${vA} ↔ ${vB}</p>`;
  } else {
    panel.innerHTML = `<div class="card-title">Propiedades</div>
      <p class="text-muted text-sm">Selecciona una VM o enlace.</p>`;
  }
}

function tdUpdateVm(id, field, value) {
  const vm = TD.vms.find(v=>v.id===id);
  if (vm) { vm[field]=value; tdUpdateSummary(); }
}

function tdUpdateLink(id, field, value) {
  const link = TD.links.find(l=>l.id===id);
  if (link) { link[field]=value; tdUpdateSummary(); }
}

function tdUpdateSummary() {
  const el = document.getElementById('td-summary');
  if (!el) return;
  const vmLines  = TD.vms.map(v=>`<div style="padding:2px 0">${v.name} — ${v.ram}MB/${v.vcpu}vCPU</div>`).join('');
  const lnkLines = TD.links.map((l,i)=>{
    const a=TD.vms.find(v=>v.id===l.vmA)?.name||'?';
    const b=TD.vms.find(v=>v.id===l.vmB)?.name||'?';
    return `<div style="padding:2px 0;color:${tdLinkColor(i)}">${l.name}: ${a}↔${b}</div>`;
  }).join('');
  el.innerHTML = `
    <div style="margin-bottom:6px">VMs: <b>${TD.vms.length}</b> | Links: <b>${TD.links.length}</b></div>
    <div style="font-size:11px;color:var(--text-muted)">${vmLines}${lnkLines}</div>`;
}

async function tdSubmit() {
  const name = document.getElementById('td-name')?.value?.trim();
  if (!name)            { toast('Ingresa un nombre para el Slice','error'); return; }
  if (!TD.vms.length)   { toast('Agrega al menos una VM','error'); return; }
  if (!TD.links.length) { toast('Dibuja al menos un enlace entre VMs','error'); return; }

  const vms = TD.vms.map(vm => ({
    name: vm.name, base_image: vm.base_image, ram: vm.ram, vcpu: vm.vcpu,
  }));

  // Cada link del diseñador se convierte en un enlace vm_a/vm_b con nombres de VM
  const links = TD.links.map(l => {
    const vmA = TD.vms.find(v => v.id === l.vmA);
    const vmB = TD.vms.find(v => v.id === l.vmB);
    return { vm_a: vmA?.name || '', iface_a: 'eth0', vm_b: vmB?.name || '', iface_b: 'eth0' };
  });

  try {
    await api('POST', '/slices/', { name, vms, links });
    toast('Slice enviado para aprobación','success');
    if (TD.animFrame) cancelAnimationFrame(TD.animFrame);
    navigate('my-slices');
  } catch(e) { toast(e.message,'error'); }
}

// ── Slice detail modal ────────────────────────────────────────
async function viewSliceDetail(id) {
  try {
    const s = await api('GET', `/slices/${id}`);
    const vmsHTML = s.vms.map(vm => `
      <div style="margin-bottom:12px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:6px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <strong style="font-size:13px">${vm.name}</strong>
          ${badge(vm.status)}
        </div>
        <div style="font-size:12px;color:var(--text-muted);display:flex;gap:16px;margin-bottom:8px">
          ${vm.worker_id  ? `<span>Worker: ${vm.worker_id}</span>`   : ''}
          ${vm.vnc_port   ? `<span>VNC: ${vm.vnc_port}</span>`       : ''}
          ${vm.process_id ? `<span>PID: ${vm.process_id}</span>`     : ''}
        </div>
        ${vm.interfaces.length ? `
          <div class="table-wrap"><table>
            <thead><tr><th>Interfaz</th><th>IP</th><th>TAP</th><th>VLAN inner</th></tr></thead>
            <tbody>${vm.interfaces.map(i => `
              <tr>
                <td class="mono">${i.interface_name || '—'}</td>
                <td class="mono">${i.ip_address     || '—'}</td>
                <td class="mono text-muted">${i.tap_name  || '—'}</td>
                <td class="mono text-muted">${i.vlan_inner != null ? i.vlan_inner : '—'}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>` : '<p class="text-muted text-sm">Sin interfaces asignadas aún.</p>'}
      </div>`).join('') || '<p class="text-muted text-sm">No hay VMs.</p>';

    openModal(`Slice #${s.id} — ${s.name}`, `
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

// ── Delete slice ──────────────────────────────────────────────
async function deleteSlice(id) {
  if (!confirm(`¿Eliminar slice #${id}? Se crearán tareas de limpieza.`)) return;
  try {
    await api('DELETE', `/slices/${id}`);
    toast('Slice en proceso de eliminación', 'success');
    navigate(state.view);
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── SLICE_ADMIN: pendientes ───────────────────────────────────
async function renderPending() {
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const { slices } = await api('GET', '/slices/');
    const pending = slices.filter(s => s.status === 'PENDING_APPROVAL');

    if (pending.length === 0) {
      content.innerHTML = `<div class="card"><div class="empty-state"><div class="empty-icon">✅</div><p>No hay solicitudes pendientes.</p></div></div>`;
      return;
    }

    content.innerHTML = `<div class="card">
      <div class="card-title">Solicitudes pendientes de aprobación</div>
      <div class="table-wrap"><table>
        <thead><tr><th>ID</th><th>Nombre</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>${pending.map(s => `
          <tr>
            <td class="text-muted">#${s.id}</td>
            <td><strong>${s.name}</strong></td>
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
    content.innerHTML = `<div class="card"><p class="error-msg">${e.message}</p></div>`;
  }
}

async function approveSlice(id) {
  try {
    await api('POST', `/slices/${id}/approve`);
    toast(`Slice #${id} aprobado`, 'success');
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

// ── All slices (ADMIN views) ──────────────────────────────────
async function renderAllSlices() {
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const { slices } = await api('GET', '/slices/');

    const actions = state.user.role === 'SLICE_ADMIN'
      ? s => `
          <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver</button>
          ${s.status === 'PENDING_APPROVAL'
            ? `<button class="btn btn-success btn-sm" onclick="approveSlice(${s.id})">Aprobar</button>
               <button class="btn btn-danger  btn-sm" onclick="rejectSlice(${s.id})">Rechazar</button>`
            : ''}`
      : s => `
          <button class="btn btn-ghost btn-sm" onclick="viewSliceDetail(${s.id})">Ver</button>
          <button class="btn btn-ghost  btn-sm" onclick="viewNetDetail(${s.id})">Red</button>
          <button class="btn btn-danger btn-sm" onclick="deleteSlice(${s.id})">Eliminar</button>`;

    content.innerHTML = slices.length === 0
      ? `<div class="card"><div class="empty-state"><div class="empty-icon">📭</div><p>No hay slices en el sistema.</p></div></div>`
      : `<div class="card">
          <div class="card-title">Todos los Slices</div>
          <div class="table-wrap"><table>
            <thead><tr><th>ID</th><th>Nombre</th><th>Estado</th><th>VMs</th><th>Acciones</th></tr></thead>
            <tbody>${slices.map(s => `
              <tr>
                <td class="text-muted">#${s.id}</td>
                <td><strong>${s.name}</strong></td>
                <td>${badge(s.status)}</td>
                <td class="text-muted">${s.vms_count}</td>
                <td style="display:flex;gap:6px;flex-wrap:wrap">${actions(s)}</td>
              </tr>`).join('')}
            </tbody>
          </table></div>
        </div>`;
  } catch (e) {
    content.innerHTML = `<div class="card"><p class="error-msg">${e.message}</p></div>`;
  }
}

// ── SYSTEM_ADMIN: networking ──────────────────────────────────
async function renderNetworking() {
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;

  try {
    const [slicesData, vlans] = await Promise.all([
      api('GET', '/slices/'),
      api('GET', '/networking/vlans/available'),
    ]);
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
      </div>

      <div class="card">
        <div class="card-title">Slices con red asignada</div>
        ${withNet.length === 0
          ? '<div class="empty-state"><div class="empty-icon">🔌</div><p>No hay slices con red asignada.</p></div>'
          : `<div class="table-wrap"><table>
              <thead><tr><th>Slice</th><th>Estado</th><th>Acciones</th></tr></thead>
              <tbody>${withNet.map(s => `
                <tr>
                  <td><strong>#${s.id}</strong> — ${s.name}</td>
                  <td>${badge(s.status)}</td>
                  <td style="display:flex;gap:6px">
                    <button class="btn btn-ghost btn-sm" onclick="viewNetDetail(${s.id})">Ver plan de red</button>
                    <button class="btn btn-ghost btn-sm" onclick="viewOvsCommands(${s.id})">Comandos OvS</button>
                    <button class="btn btn-ghost btn-sm" onclick="viewSecurityPanel(${s.id})">Seguridad</button>
                  </td>
                </tr>`).join('')}
              </tbody>
            </table></div>`}
      </div>`;
  } catch (e) {
    content.innerHTML = `<div class="card"><p class="error-msg">${e.message}</p></div>`;
  }
}

async function viewNetDetail(sliceId) {
  try {
    const net = await api('GET', `/networking/networks/${sliceId}`);
    const rows = net.networks.map(n => `
      <div class="net-plan-row">
        <span class="tag tag-inner">VI:${n.vlan_inner}</span>
        <span class="tag tag-slice">VS:${n.vlan_slice}</span>
        <span class="tag ${n.is_remote ? 'tag-remote' : 'tag-local'}">${n.is_remote ? 'REMOTO' : 'LOCAL'}</span>
        <span class="mono" style="flex:1">${n.subnet_cidr}</span>
        <span class="text-muted text-xs">${n.is_remote ? '🔀' : '🔗'}</span>
      </div>
      <div style="padding:0 12px 10px">
        ${n.interfaces.map(i => `
          <div style="display:flex;gap:12px;font-size:11px;color:var(--text-muted);padding:3px 0">
            <span class="mono">${i.tap_name}</span>
            <span>${i.ip_address}</span>
            <span class="mono" style="color:var(--text-dim)">${i.mac_address}</span>
            <span>VM${i.vm_id} @ W${i.worker_id}</span>
          </div>`).join('')}
      </div>`).join('');

    openModal(`Red del Slice #${sliceId} — Vlan-Slice: ${net.vlan_slice} / Bridge: ${net.bridge_name}`, `
      <div style="margin-bottom:12px;font-size:12px;color:var(--text-muted)">
        <span class="tag tag-inner">VI = Vlan-Inner (local al Br-Slice)</span>
        <span class="tag tag-slice">VS = Vlan-Slice (transporte inter-worker)</span>
      </div>
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;overflow:hidden">
        ${rows}
      </div>`);
  } catch (e) { toast(e.message, 'error'); }
}

async function viewOvsCommands(sliceId) {
  try {
    const ovs = await api('GET', `/networking/ovs/commands/${sliceId}`);
    const workersHTML = ovs.workers.map(w => `
      <div class="worker-block">
        <div class="worker-block-title">Worker ${w.worker_id}</div>
        <div class="code-block"><pre>${w.commands.join('\n')}</pre></div>
      </div>`).join('');

    openModal(`Comandos OvS — Slice #${sliceId} (Vlan-Slice: ${ovs.vlan_slice})`, workersHTML);
  } catch (e) { toast(e.message, 'error'); }
}

async function viewSecurityPanel(sliceId) {
  try {
    const [rules, flows] = await Promise.all([
      api('GET', `/networking/security/rules/${sliceId}`),
      api('GET', `/networking/security/flows/${sliceId}`),
    ]);

    const rulesHTML = rules.length === 0
      ? '<p class="text-muted text-sm">No hay reglas definidas.</p>'
      : `<div class="table-wrap"><table>
          <thead><tr><th>ID</th><th>Src VM</th><th>Dst VM</th><th>Proto</th><th>Puerto</th><th>Acción</th><th></th></tr></thead>
          <tbody>${rules.map(r => `
            <tr>
              <td class="text-muted">${r.id}</td>
              <td>VM${r.src_vm_id}</td>
              <td>VM${r.dst_vm_id}</td>
              <td class="mono">${r.protocol}</td>
              <td class="mono">${r.port_min != null ? `${r.port_min}${r.port_max !== r.port_min ? '–'+r.port_max : ''}` : '*'}</td>
              <td>${badge(r.action === 'ALLOW' ? 'ACTIVE' : 'FAILED')}</td>
              <td><button class="btn-icon" onclick="deleteRule(${r.id}, ${sliceId})">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
              </button></td>
            </tr>`).join('')}
          </tbody>
        </table></div>`;

    const flowsHTML = [...flows.setup_flows, ...flows.policy_flows]
      .map(f => f.flow).join('\n');

    openModal(`Seguridad — Slice #${sliceId}`, `
      <div class="card-title" style="margin-bottom:10px">Reglas de seguridad</div>
      ${rulesHTML}

      <div style="margin-top:16px;margin-bottom:10px">
        <div class="card-title" style="margin-bottom:8px">Nueva regla</div>
        <div class="rule-form" id="new-rule-form">
          <div class="field"><label>VM origen</label><input type="number" id="r-src" placeholder="ID VM" /></div>
          <div class="field"><label>VM destino</label><input type="number" id="r-dst" placeholder="ID VM" /></div>
          <div class="field"><label>Protocolo</label>
            <select id="r-proto">
              <option value="any">any</option>
              <option value="tcp">tcp</option>
              <option value="udp">udp</option>
              <option value="icmp">icmp</option>
            </select>
          </div>
          <div class="field"><label>Puerto</label><input type="number" id="r-port" placeholder="80 (opcional)" /></div>
          <div class="field"><label>Acción</label>
            <select id="r-action"><option value="ALLOW">ALLOW</option><option value="DENY">DENY</option></select>
          </div>
          <div class="field"><label>Prioridad</label><input type="number" id="r-prio" value="100" /></div>
          <div class="field" style="align-self:flex-end">
            <button class="btn btn-primary" onclick="addRule(${sliceId})">Agregar</button>
          </div>
        </div>
      </div>

      <div class="divider"></div>
      <div class="card-title" style="margin-bottom:8px">Flujos OpenFlow generados</div>
      <div class="code-block"><pre>${flowsHTML || '(sin flujos de política)'}</pre></div>
    `);
  } catch (e) { toast(e.message, 'error'); }
}

async function addRule(sliceId) {
  const src   = parseInt(document.getElementById('r-src').value);
  const dst   = parseInt(document.getElementById('r-dst').value);
  const proto = document.getElementById('r-proto').value;
  const port  = parseInt(document.getElementById('r-port').value) || null;
  const action = document.getElementById('r-action').value;
  const prio  = parseInt(document.getElementById('r-prio').value) || 100;

  if (!src || !dst) { toast('Ingresa IDs de VM origen y destino', 'error'); return; }
  try {
    await api('POST', '/networking/security/rules', {
      slice_id: sliceId,
      src_vm_id: src,
      dst_vm_id: dst,
      protocol: proto,
      port_min: port,
      port_max: port,
      action,
      priority: prio,
    });
    toast('Regla creada', 'success');
    closeModal();
    viewSecurityPanel(sliceId);
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteRule(ruleId, sliceId) {
  try {
    await api('DELETE', `/networking/security/rules/${ruleId}`);
    toast('Regla eliminada', 'info');
    closeModal();
    viewSecurityPanel(sliceId);
  } catch (e) { toast(e.message, 'error'); }
}

// ── Init ──────────────────────────────────────────────────────
document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('btn-login');
  const err = document.getElementById('login-error');
  btn.disabled = true;
  btn.textContent = 'Ingresando...';
  err.classList.add('hidden');
  try {
    await login(
      document.getElementById('inp-username').value.trim(),
      document.getElementById('inp-password').value,
    );
    showApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Ingresar';
  }
});

document.getElementById('btn-logout').addEventListener('click', logout);
document.getElementById('btn-modal-close').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
});

// Expose functions needed from inline onclick
Object.assign(window, {
  navigate, viewSliceDetail, deleteSlice,
  approveSlice, rejectSlice,
  viewNetDetail, viewOvsCommands, viewSecurityPanel,
  addRule, deleteRule,
  // topology designer
  tdSetMode, tdAddVM, tdDeleteSelected, tdSubmit,
  tdUpdateVm, tdUpdateLink,
});

// Auto-login si hay token guardado
if (state.token && state.user) {
  showApp();
} else {
  showLogin();
}
