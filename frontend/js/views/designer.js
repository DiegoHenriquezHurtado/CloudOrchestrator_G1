// ── Diseñador visual de topologías (Solicitar/Crear Slice) ────
// Contrato real del backend (POST /slices/):
//   linux:     vms:[{name, base_image, flavor_id}]  ← el flavor define RAM/vCPU/disco
//   openstack: vms:[{name, base_image, flavor}] + networks:[{name,cidr,is_provider}]
//              (solo SLICE_ADMIN / SYSTEM_ADMIN)
//   links:     [{vm_a, iface_a, vm_b, iface_b}] — "internet" como extremo = salida WAN

let TD = null;

const TD_LINK_COLORS = [
  '#22c55e','#06b6d4','#f59e0b','#8b5cf6',
  '#ec4899','#ef4444','#38bdf8','#f43f5e',
];
const TD_VM_W = 100, TD_VM_H = 38, TD_VM_R = 8;
const TD_INTERNET_NAME = 'internet';

function tdLinkColor(idx) { return TD_LINK_COLORS[idx % TD_LINK_COLORS.length]; }

function tdIsAdmin() {
  return ['SLICE_ADMIN', 'SYSTEM_ADMIN'].includes(state.user.role);
}

// SLICE_ADMIN/SYSTEM_ADMIN guardan el slice como Borrador (sin desplegar); STUDENT envía solicitud.
function tdSubmitLabel() {
  return tdIsAdmin() ? 'Guardar Borrador' : 'Enviar solicitud';
}

// Botón(es) de envío: normal al crear; "Guardar cambios" + "Guardar como nueva…" al editar un Borrador.
function tdSubmitButtonsHTML() {
  if (TD.editingSliceId) {
    return `
      <button class="btn btn-ghost" onclick="tdSubmit('new')" id="btn-td-submit-new">Guardar como nueva…</button>
      <button class="btn btn-primary" onclick="tdSubmit('update')" id="btn-td-submit">Guardar cambios</button>`;
  }
  return `<button class="btn btn-primary" onclick="tdSubmit()" id="btn-td-submit">${tdSubmitLabel()}</button>`;
}

// editId/editData: al editar un Borrador existente (viene de editSlice() en slices.js,
// que ya trae editData desde GET /slices/{id}/export con la forma de SliceCreate).
function renderNewSlice(editId, editData) {
  beginRender(); // invalida fetches pendientes de la vista anterior
  if (TD?.animFrame) cancelAnimationFrame(TD.animFrame);

  TD = {
    vms: [], links: [],
    nextVmId: 1, nextLinkId: 1,
    selected: null,   // {type:'vm'|'link', id}
    mode: 'select',
    connectFrom: null,
    drag: null,
    mouseX: 0, mouseY: 0,
    animFrame: null,
    target: editData?.iaas_target || 'linux',   // 'linux' | 'openstack'
    flavors: [],            // catálogo /flavors/ (linux)
    images: [],             // catálogo /images/ (linux)
    osFlavors: [],          // catálogo /openstack/flavors (Nova)
    osImages: [],           // catálogo /openstack/images (Glance)
    osCatalogsLoaded: false,
    editingSliceId: editId || null,
  };

  const targetSelector = tdIsAdmin() ? `
    <div class="field" style="margin:0">
      <select id="td-target" onchange="tdSetTarget(this.value)" title="Plataforma destino">
        <option value="linux" ${TD.target === 'linux' ? 'selected' : ''}>Cluster Linux</option>
        <option value="openstack" ${TD.target === 'openstack' ? 'selected' : ''}>OpenStack</option>
      </select>
    </div>` : '';

  const content = document.getElementById('content');
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 240px;gap:14px;height:calc(100vh - 110px)">

      <div style="display:flex;flex-direction:column;gap:10px;min-height:0">
        <!-- Toolbar -->
        <div class="card" style="padding:10px 14px;margin:0;flex-shrink:0">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <div class="field" style="margin:0;flex:1;min-width:160px">
              <input type="text" id="td-name" placeholder="Nombre del Slice" style="font-weight:600" value="${esc(editData?.name || '')}" />
            </div>
            ${targetSelector}
            <div style="display:flex;gap:6px;align-items:center">
              <button class="btn btn-ghost btn-sm" id="btn-td-select" onclick="tdSetMode('select')" title="Seleccionar / mover VMs">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l14 9-7 1-4 7z"/></svg> Mover
              </button>
              <button class="btn btn-ghost btn-sm" id="btn-td-connect" onclick="tdSetMode('connect')" title="Dibujar enlace entre VMs">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg> Enlazar
              </button>
              <div style="width:1px;height:20px;background:var(--border)"></div>
              <button class="btn btn-ghost btn-sm" onclick="tdAddVM()">+ VM</button>
              <button class="btn btn-ghost btn-sm" onclick="tdAddInternet()" title="Nodo de salida a Internet">+ Internet</button>
              <button class="btn btn-ghost btn-sm" onclick="tdOpenTopoModal()">Plantilla</button>
              <button class="btn btn-danger btn-sm" onclick="tdDeleteSelected()">Eliminar</button>
            </div>
            ${tdSubmitButtonsHTML()}
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
            <div><b style="color:var(--text-muted)">Enlazar</b> — modo Enlazar, click en 2 nodos</div>
            <div><b style="color:var(--text-muted)">Internet</b> — enlaza una VM al nodo internet</div>
            <div><b style="color:var(--text-muted)">Borrar</b> — selecciona + Eliminar</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal topología predefinida -->
    <div id="td-topo-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.65);
         z-index:1000;align-items:center;justify-content:center">
      <div class="card" style="width:340px;margin:0;padding:20px 24px;gap:14px;display:flex;flex-direction:column">
        <div class="card-title" style="margin-bottom:0">Topología predefinida</div>
        <div class="field" style="margin:0">
          <label>Tipo</label>
          <select id="td-topo-type" style="width:100%">
            <option value="ring">Anillo — cada VM conectada a la siguiente en círculo</option>
            <option value="star">Estrella — un hub central conectado a todos los nodos</option>
            <option value="line">Lineal — VMs en cadena de extremo a extremo</option>
          </select>
        </div>
        <div class="field" style="margin:0">
          <label>Número de VMs</label>
          <input type="number" id="td-topo-n" value="4" min="2" max="20"
                 style="width:100%;box-sizing:border-box" />
        </div>
        <div id="td-topo-linux-fields">
          <div class="field" style="margin:0 0 10px">
            <label>Imagen base</label>
            <select id="td-topo-img" style="width:100%">
              <option value="" disabled selected>Selecciona una imagen</option>
            </select>
          </div>
          <div class="field" style="margin:0">
            <label>Flavor</label>
            <select id="td-topo-flavor" style="width:100%">
              <option value="" disabled selected>Selecciona un flavor</option>
            </select>
          </div>
        </div>
        <div id="td-topo-os-fields" style="display:none">
          <div class="field" style="margin:0 0 10px">
            <label>Imagen (Glance)</label>
            <select id="td-topo-os-img" style="width:100%">
              <option value="" disabled selected>Selecciona una imagen</option>
            </select>
          </div>
          <div class="field" style="margin:0">
            <label>Flavor (Nova)</label>
            <select id="td-topo-os-flavor" style="width:100%">
              <option value="" disabled selected>Selecciona un flavor</option>
            </select>
          </div>
        </div>
        <p class="text-muted text-sm" style="margin:0">
          Puedes editar cada VM individualmente y seguir añadiendo VMs o enlaces después.
        </p>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn-ghost btn-sm" onclick="tdCloseTopoModal()">Cancelar</button>
          <button class="btn btn-primary btn-sm" onclick="tdApplyTemplate()">Aplicar</button>
        </div>
      </div>
    </div>`;

  tdLoadCatalogs();
  if (TD.target === 'openstack') tdLoadOSCatalogs();
  setTimeout(() => tdInitCanvas(editData), 20);
}

// Carga catálogos de imágenes y flavors una sola vez por sesión de diseño
async function tdLoadCatalogs() {
  try {
    const [imgs, flavs] = await Promise.allSettled([
      api('GET', '/images/'),
      api('GET', '/flavors/'),
    ]);
    if (imgs.status === 'fulfilled')  TD.images  = imgs.value.images || [];
    if (flavs.status === 'fulfilled') TD.flavors = flavs.value || [];
  } catch { /* los selects mostrarán "sin datos" */ }
}

function tdSetTarget(target) {
  TD.target = target;
  const btn = document.getElementById('btn-td-submit');
  if (btn) btn.textContent = tdPrimaryButtonLabel();
  if (target === 'openstack' && !TD.osCatalogsLoaded) tdLoadOSCatalogs();
  tdRenderProps();
  tdSetHint(TD.editingSliceId ? 'Editando Borrador existente' : (tdIsAdmin() ? 'Se guardará como Borrador (sin desplegar aún)' : ''));
}

// Carga catálogos de OpenStack (Nova/Glance) una sola vez, bajo demanda
async function tdLoadOSCatalogs() {
  TD.osCatalogsLoaded = true;
  try {
    const [flavs, imgs] = await Promise.allSettled([
      api('GET', '/openstack/flavors'),
      api('GET', '/openstack/images'),
    ]);
    if (flavs.status === 'fulfilled') TD.osFlavors = flavs.value.flavors || [];
    if (imgs.status === 'fulfilled')  TD.osImages  = imgs.value.images || [];
  } catch { /* los selects mostrarán "sin datos" */ }
  tdRenderProps();
  const modal = document.getElementById('td-topo-modal');
  if (modal && modal.style.display !== 'none') tdOpenTopoModal();
}

// ── Canvas init + interacción ─────────────────────────────────
function tdInitCanvas(editData) {
  const canvas = document.getElementById('td-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    canvas.width  = r.width;
    canvas.height = r.height;
  }
  resize();

  if (editData) tdLoadFromExport(editData, canvas.width, canvas.height);

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

  tdSetMode('select');
  tdRenderProps();
  tdUpdateSummary();
}

// ── Preview de topología de solo lectura (usada por slices.js al ver un slice) ──
// Dibuja una sola vez, sin listeners ni loop de animación; no toca el TD del diseñador.
function tdRenderStatic(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const r = canvas.parentElement.getBoundingClientRect();
  canvas.width = r.width;
  canvas.height = r.height;
  const ctx = canvas.getContext('2d');

  const prevTD = TD;
  TD = { vms: [], links: [], nextVmId: 1, nextLinkId: 1, selected: null, mode: 'view', connectFrom: null, mouseX: 0, mouseY: 0 };
  tdLoadFromExport(data, canvas.width, canvas.height);
  tdRender(ctx, canvas.width, canvas.height);
  TD = prevTD;
}

// ── Carga una topología existente (desde GET /slices/{id}/export) en el canvas ──
const TD_INTERNET_ALIASES = ['internet', 'inet', 'wan', 'external', 'external-provider'];
function tdIsInternetName(name) { return TD_INTERNET_ALIASES.includes(String(name || '').toLowerCase()); }

function tdLoadFromExport(data, W, H) {
  TD.vms = []; TD.links = [];
  TD.nextVmId = 1; TD.nextLinkId = 1;

  const nameToId = {};
  const n = (data.vms || []).length;
  const cx = W / 2, cy = H / 2, r = Math.min(W, H) * 0.34;

  (data.vms || []).forEach((vm, i) => {
    const id = TD.nextVmId++;
    const angle = n > 1 ? (2 * Math.PI * i / n) - Math.PI / 2 : -Math.PI / 2;
    TD.vms.push({
      id, name: vm.name,
      base_image: vm.base_image || '',
      flavor_id: vm.flavor_id ?? null,
      flavor: vm.flavor || '',
      isInternet: false,
      x: n > 1 ? cx + r * Math.cos(angle) : cx,
      y: n > 1 ? cy + r * Math.sin(angle) : cy,
    });
    nameToId[vm.name] = id;
  });

  const links = data.links || [];
  let internetId = null;
  if (links.some(l => tdIsInternetName(l.vm_a) || tdIsInternetName(l.vm_b))) {
    internetId = TD.nextVmId++;
    TD.vms.push({ id: internetId, name: TD_INTERNET_NAME, isInternet: true, x: W - 110, y: 55 });
  }

  links.forEach(l => {
    const aId = tdIsInternetName(l.vm_a) ? internetId : nameToId[l.vm_a];
    const bId = tdIsInternetName(l.vm_b) ? internetId : nameToId[l.vm_b];
    if (aId == null || bId == null) return;
    const id = TD.nextLinkId++;
    TD.links.push({ id, name: `link-${id}`, vmA: aId, vmB: bId });
  });
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
      tdSetHint('Ahora haz click en el nodo de destino');
    } else if (TD.connectFrom !== vm.id) {
      const from = TD.vms.find(v => v.id === TD.connectFrom);
      if (from?.isInternet && vm.isInternet) { TD.connectFrom = null; return; }
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
      tdSetHint('Enlace creado. Haz click en otro nodo de origen o cambia de modo.');
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

// ── Render del canvas ─────────────────────────────────────────
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

  // Línea punteada en modo enlazar
  if (TD.mode==='connect' && TD.connectFrom) {
    const vm = TD.vms.find(v=>v.id===TD.connectFrom);
    if (vm) {
      ctx.save();
      ctx.setLineDash([5,4]); ctx.strokeStyle='rgba(139,92,246,0.5)'; ctx.lineWidth=1.5;
      ctx.beginPath(); ctx.moveTo(vm.x,vm.y); ctx.lineTo(TD.mouseX,TD.mouseY); ctx.stroke();
      ctx.restore();
    }
  }

  // Nodos
  TD.vms.forEach(vm => {
    const x=vm.x-TD_VM_W/2, y=vm.y-TD_VM_H/2;
    const sel  = TD.selected?.type==='vm' && TD.selected?.id===vm.id;
    const src  = TD.connectFrom===vm.id;
    const base = vm.isInternet ? '#06b6d4' : '#a78bfa';
    ctx.save();
    ctx.shadowColor = src ? 'rgba(139,92,246,0.7)' : (vm.isInternet ? 'rgba(6,182,212,0.4)' : 'rgba(139,92,246,0.28)');
    ctx.shadowBlur  = sel||src ? 22 : 9;
    ctx.fillStyle   = sel ? (vm.isInternet ? 'rgba(6,182,212,0.16)' : 'rgba(139,92,246,0.16)') : (vm.isInternet ? '#081a1e' : '#12081e');
    ctx.strokeStyle = sel||src ? base : (vm.isInternet ? 'rgba(6,182,212,0.6)' : 'rgba(139,92,246,0.55)');
    ctx.lineWidth   = sel||src ? 2 : 1.2;
    tdRrect(ctx,x,y,TD_VM_W,TD_VM_H,TD_VM_R); ctx.fill(); ctx.stroke();
    ctx.font='600 12px "SFMono-Regular",Consolas,monospace';
    ctx.fillStyle = sel ? base : base + 'cc';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText(vm.isInternet ? '🌐 internet' : vm.name, vm.x, vm.y);
    ctx.restore();
  });

  if (TD.vms.length===0) {
    ctx.save();
    ctx.font='14px sans-serif'; ctx.fillStyle='rgba(139,92,246,0.22)';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText('Haz click en "+ VM" para agregar máquinas virtuales', W/2, H/2);
    ctx.restore();
  }
}

// ── Acciones del diseñador ────────────────────────────────────
function tdAddVM() {
  const canvas = document.getElementById('td-canvas');
  const W = canvas?.width || 600, H = canvas?.height || 400;
  const id = TD.nextVmId++;
  TD.vms.push({
    id, name:`VM${id}`,
    base_image:'', flavor_id:null, flavor:'',
    isInternet:false,
    x: 80 + Math.random()*(W-160),
    y: 60 + Math.random()*(H-120),
  });
  TD.selected = { type:'vm', id };
  tdRenderProps(); tdUpdateSummary();
}

function tdAddInternet() {
  if (TD.vms.some(v => v.isInternet)) {
    toast('Ya existe un nodo Internet en la topología', 'error');
    return;
  }
  const canvas = document.getElementById('td-canvas');
  const W = canvas?.width || 600;
  const id = TD.nextVmId++;
  TD.vms.push({
    id, name: TD_INTERNET_NAME, isInternet: true,
    x: W - 110, y: 55,
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

// ── Plantillas ────────────────────────────────────────────────
function tdOpenTopoModal() {
  document.getElementById('td-topo-modal').style.display = 'flex';
  const isOS = TD.target === 'openstack';
  document.getElementById('td-topo-linux-fields').style.display = isOS ? 'none' : '';
  document.getElementById('td-topo-os-fields').style.display    = isOS ? '' : 'none';

  if (!isOS) {
    const selImg = document.getElementById('td-topo-img');
    selImg.innerHTML = TD.images.length
      ? `<option value="" disabled selected>Selecciona una imagen</option>` +
        TD.images.map(img => `<option value="${esc(img.name)}">${esc(img.name)}</option>`).join('')
      : `<option value="" disabled selected>No hay imágenes disponibles</option>`;

    const selFlav = document.getElementById('td-topo-flavor');
    selFlav.innerHTML = TD.flavors.length
      ? `<option value="" disabled selected>Selecciona un flavor</option>` +
        TD.flavors.map(f => `<option value="${f.id}">${esc(f.name)} — ${f.ram}MB/${f.vcpu}vCPU/${f.disk}GB</option>`).join('')
      : `<option value="" disabled selected>No hay flavors disponibles</option>`;
  } else {
    if (!TD.osCatalogsLoaded) tdLoadOSCatalogs();
    const selImg = document.getElementById('td-topo-os-img');
    selImg.innerHTML = TD.osImages.length
      ? `<option value="" disabled selected>Selecciona una imagen</option>` +
        TD.osImages.map(img => `<option value="${esc(img.id)}">${esc(img.name)}</option>`).join('')
      : `<option value="" disabled selected>${TD.osCatalogsLoaded ? 'No hay imágenes disponibles' : 'Cargando...'}</option>`;

    const selFlav = document.getElementById('td-topo-os-flavor');
    selFlav.innerHTML = TD.osFlavors.length
      ? `<option value="" disabled selected>Selecciona un flavor</option>` +
        TD.osFlavors.map(f => `<option value="${esc(f.id)}">${esc(f.name)} — ${f.ram}MB/${f.vcpus}vCPU/${f.disk}GB</option>`).join('')
      : `<option value="" disabled selected>${TD.osCatalogsLoaded ? 'No hay flavors disponibles' : 'Cargando...'}</option>`;
  }
}
function tdCloseTopoModal() { document.getElementById('td-topo-modal').style.display = 'none'; }

function tdApplyTemplate() {
  const type = document.getElementById('td-topo-type').value;
  const n    = parseInt(document.getElementById('td-topo-n').value, 10);
  const canvas = document.getElementById('td-canvas');
  const W = canvas?.width || 600, H = canvas?.height || 400;
  const isOS = TD.target === 'openstack';

  const img      = isOS ? document.getElementById('td-topo-os-img').value.trim()    : document.getElementById('td-topo-img').value;
  const flavorId = isOS ? null : parseInt(document.getElementById('td-topo-flavor').value, 10) || null;
  const flavorOS = isOS ? document.getElementById('td-topo-os-flavor').value.trim() : '';

  if (type === 'ring' && n < 3) { toast('Anillo requiere mínimo 3 VMs', 'error'); return; }
  if (type === 'star' && n < 3) { toast('Estrella requiere mínimo 3 VMs', 'error'); return; }
  if (type === 'line' && n < 2) { toast('Lineal requiere mínimo 2 VMs', 'error'); return; }
  if (n > 20) { toast('Máximo 20 VMs por plantilla', 'error'); return; }
  if (!img) { toast('Indica la imagen base', 'error'); return; }
  if (!isOS && !flavorId) { toast('Selecciona un flavor', 'error'); return; }
  if (isOS && !flavorOS)  { toast('Indica el flavor de OpenStack', 'error'); return; }

  let result;
  if (type === 'ring') result = tdGenerateRing(n, W, H);
  else if (type === 'star') result = tdGenerateStar(n, W, H);
  else result = tdGenerateLine(n, W, H);

  result.vms.forEach(vm => {
    vm.base_image = img;
    vm.flavor_id  = flavorId;
    vm.flavor     = flavorOS;
  });

  TD.vms.push(...result.vms);
  TD.links.push(...result.links);
  TD.selected = null;
  tdRenderProps(); tdUpdateSummary(); tdCloseTopoModal();
  toast(`Plantilla aplicada: ${result.vms.length} VMs, ${result.links.length} enlaces`, 'success');
}

function tdNewTemplateVm(x, y) {
  const id = TD.nextVmId++;
  return { id, name:`VM${id}`, base_image:'', flavor_id:null, flavor:'', isInternet:false, x, y };
}

function tdGenerateRing(n, W, H) {
  const cx = W / 2, cy = H / 2, r = Math.min(W, H) * 0.34;
  const vms = [], links = [];
  for (let i = 0; i < n; i++) {
    const angle = (2 * Math.PI * i / n) - Math.PI / 2;
    vms.push(tdNewTemplateVm(cx + r * Math.cos(angle), cy + r * Math.sin(angle)));
  }
  for (let i = 0; i < n; i++) {
    const id = TD.nextLinkId++;
    links.push({ id, name: `link-${id}`, vmA: vms[i].id, vmB: vms[(i + 1) % n].id });
  }
  return { vms, links };
}

function tdGenerateStar(n, W, H) {
  const cx = W / 2, cy = H / 2, r = Math.min(W, H) * 0.34;
  const vms = [], links = [];
  const hub = tdNewTemplateVm(cx, cy);
  vms.push(hub);
  const spokes = n - 1;
  for (let i = 0; i < spokes; i++) {
    const angle = (2 * Math.PI * i / spokes) - Math.PI / 2;
    const vm = tdNewTemplateVm(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
    vms.push(vm);
    const lid = TD.nextLinkId++;
    links.push({ id: lid, name: `link-${lid}`, vmA: hub.id, vmB: vm.id });
  }
  return { vms, links };
}

function tdGenerateLine(n, W, H) {
  const margin = 90, cy = H / 2;
  const step = n > 1 ? (W - margin * 2) / (n - 1) : 0;
  const vms = [], links = [];
  for (let i = 0; i < n; i++) {
    vms.push(tdNewTemplateVm(margin + i * step, cy));
    if (i > 0) {
      const lid = TD.nextLinkId++;
      links.push({ id: lid, name: `link-${lid}`, vmA: vms[i - 1].id, vmB: vms[i].id });
    }
  }
  return { vms, links };
}

// ── Modos / panel de propiedades ──────────────────────────────
function tdSetMode(mode) {
  TD.mode = mode; TD.connectFrom = null;
  document.getElementById('btn-td-select' )?.classList.toggle('active', mode==='select');
  document.getElementById('btn-td-connect')?.classList.toggle('active', mode==='connect');
  tdSetHint(mode==='connect' ? 'Haz click en el nodo de origen del enlace' : '');
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

    if (vm.isInternet) {
      panel.innerHTML = `
        <div class="card-title">🌐 Internet</div>
        <p class="text-muted text-sm">Nodo de salida WAN. Enlaza VMs a este nodo para darles acceso a Internet.</p>`;
      return;
    }

    if (TD.target === 'openstack') {
      const osImgOptions = TD.osImages.length
        ? `<option value="" disabled ${!vm.base_image ? 'selected' : ''}>Selecciona una imagen</option>` +
          TD.osImages.map(img =>
            `<option value="${esc(img.id)}" ${img.id === vm.base_image ? 'selected' : ''}>${esc(img.name)}</option>`).join('')
        : `<option value="" disabled selected>${TD.osCatalogsLoaded ? 'No hay imágenes disponibles' : 'Cargando...'}</option>`;

      const osFlavOptions = TD.osFlavors.length
        ? `<option value="" disabled ${!vm.flavor ? 'selected' : ''}>Selecciona un flavor</option>` +
          TD.osFlavors.map(f =>
            `<option value="${esc(f.id)}" ${f.id === vm.flavor ? 'selected' : ''}>${esc(f.name)} — ${f.ram}MB/${f.vcpus}vCPU/${f.disk}GB</option>`).join('')
        : `<option value="" disabled selected>${TD.osCatalogsLoaded ? 'No hay flavors disponibles' : 'Cargando...'}</option>`;

      const osFlav = TD.osFlavors.find(f => f.id === vm.flavor);
      panel.innerHTML = `
        <div class="card-title">${esc(vm.name)}</div>
        <div class="field"><label>Nombre</label>
          <input type="text" value="${esc(vm.name)}" oninput="tdUpdateVm(${vm.id},'name',this.value)" /></div>
        <div class="field"><label>Imagen (Glance)</label>
          <select onchange="tdUpdateVm(${vm.id},'base_image',this.value)">${osImgOptions}</select></div>
        <div class="field"><label>Flavor (Nova)</label>
          <select onchange="tdUpdateVm(${vm.id},'flavor',this.value)">${osFlavOptions}</select></div>
        ${osFlav ? `<p class="text-muted text-xs" style="margin-top:6px">RAM ${osFlav.ram} MB · ${osFlav.vcpus} vCPU · ${osFlav.disk} GB disco</p>` : ''}`;
      return;
    }

    // linux: imagen del Image Manager + flavor del catálogo
    const imgOptions = TD.images.length
      ? `<option value="" disabled ${!vm.base_image ? 'selected' : ''}>Selecciona una imagen</option>` +
        TD.images.map(img =>
          `<option value="${esc(img.name)}" ${img.name === vm.base_image ? 'selected' : ''}>${esc(img.name)}</option>`).join('')
      : `<option value="" disabled selected>No hay imágenes disponibles</option>`;

    const flavOptions = TD.flavors.length
      ? `<option value="" disabled ${!vm.flavor_id ? 'selected' : ''}>Selecciona un flavor</option>` +
        TD.flavors.map(f =>
          `<option value="${f.id}" ${f.id === vm.flavor_id ? 'selected' : ''}>${esc(f.name)} — ${f.ram}MB/${f.vcpu}vCPU/${f.disk}GB</option>`).join('')
      : `<option value="" disabled selected>No hay flavors disponibles</option>`;

    const flav = TD.flavors.find(f => f.id === vm.flavor_id);
    panel.innerHTML = `
      <div class="card-title">${esc(vm.name)}</div>
      <div class="field"><label>Nombre</label>
        <input type="text" value="${esc(vm.name)}" oninput="tdUpdateVm(${vm.id},'name',this.value)" /></div>
      <div class="field"><label>Imagen base</label>
        <select onchange="tdUpdateVm(${vm.id},'base_image',this.value)">${imgOptions}</select></div>
      <div class="field"><label>Flavor</label>
        <select onchange="tdUpdateVm(${vm.id},'flavor_id',+this.value)">${flavOptions}</select></div>
      ${flav ? `<p class="text-muted text-xs" style="margin-top:6px">RAM ${flav.ram} MB · ${flav.vcpu} vCPU · ${flav.disk} GB disco</p>` : ''}`;
  } else if (s?.type==='link') {
    const link = TD.links.find(l=>l.id===s.id);
    if (!link) return;
    const vA = TD.vms.find(v=>v.id===link.vmA)?.name||'?';
    const vB = TD.vms.find(v=>v.id===link.vmB)?.name||'?';
    panel.innerHTML = `
      <div class="card-title">Enlace</div>
      <p class="text-muted text-sm" style="margin-top:6px">${esc(vA)} ↔ ${esc(vB)}</p>`;
  } else {
    panel.innerHTML = `<div class="card-title">Propiedades</div>
      <p class="text-muted text-sm">Selecciona una VM o enlace.</p>`;
  }
}

function tdUpdateVm(id, field, value) {
  const vm = TD.vms.find(v=>v.id===id);
  if (!vm) return;
  vm[field]=value;
  if (field === 'flavor_id' || (field === 'flavor' && TD.target === 'openstack')) tdRenderProps(); // refresca specs del flavor
  tdUpdateSummary();
}

function tdUpdateSummary() {
  const el = document.getElementById('td-summary');
  if (!el) return;
  const realVms = TD.vms.filter(v => !v.isInternet);
  const vmLines = realVms.map(v => {
    let spec;
    if (TD.target === 'openstack') {
      const f = TD.osFlavors.find(fl => fl.id === v.flavor);
      spec = f ? f.name : (v.flavor || 'sin flavor');
    } else {
      const f = TD.flavors.find(fl => fl.id === v.flavor_id);
      spec = f ? f.name : 'sin flavor';
    }
    return `<div style="padding:2px 0">${esc(v.name)} — ${esc(spec)}</div>`;
  }).join('');
  const lnkLines = TD.links.map((l,i)=>{
    const a=TD.vms.find(v=>v.id===l.vmA)?.name||'?';
    const b=TD.vms.find(v=>v.id===l.vmB)?.name||'?';
    return `<div style="padding:2px 0;color:${tdLinkColor(i)}">${l.name}: ${esc(a)}↔${esc(b)}</div>`;
  }).join('');
  el.innerHTML = `
    <div style="margin-bottom:6px">VMs: <b>${realVms.length}</b> | Links: <b>${TD.links.length}</b></div>
    <div style="font-size:11px;color:var(--text-muted)">${vmLines}${lnkLines}</div>`;
}

// ── Envío ─────────────────────────────────────────────────────
// mode: undefined (crear/enviar solicitud) | 'update' (guardar cambios en el mismo
// Borrador editado) | 'new' (guardar la edición como una topología nueva, con nombre propio)
function tdSubmit(mode) {
  const name = document.getElementById('td-name')?.value?.trim();
  const realVms = TD.vms.filter(v => !v.isInternet);

  if (!name)            { toast('Ingresa un nombre para el Slice','error'); return; }
  if (!realVms.length)  { toast('Agrega al menos una VM','error'); return; }
  if (!TD.links.length) { toast('Dibuja al menos un enlace','error'); return; }

  const isOS = TD.target === 'openstack';

  for (const vm of realVms) {
    if (!vm.base_image) { toast(`La VM "${vm.name}" no tiene imagen base`, 'error'); return; }
    if (!isOS && !vm.flavor_id) { toast(`La VM "${vm.name}" no tiene flavor asignado`, 'error'); return; }
    if (isOS && !vm.flavor)     { toast(`La VM "${vm.name}" no tiene flavor de OpenStack`, 'error'); return; }
  }

  // Interfaces: eth0, eth1... según cuántos enlaces toque cada VM
  // (los tap names en los workers se derivan de este nombre y deben ser únicos)
  const ifaceCount = {};
  const nextIface = vmName => {
    ifaceCount[vmName] = (ifaceCount[vmName] ?? -1) + 1;
    return `eth${ifaceCount[vmName]}`;
  };

  const links = TD.links.map(l => {
    const vmA = TD.vms.find(v => v.id === l.vmA);
    const vmB = TD.vms.find(v => v.id === l.vmB);
    return {
      vm_a: vmA?.name || '',
      iface_a: vmA?.isInternet ? 'eth0' : nextIface(vmA?.name),
      vm_b: vmB?.name || '',
      iface_b: vmB?.isInternet ? 'eth0' : nextIface(vmB?.name),
    };
  });

  const payload = { name, iaas_target: TD.target, links };

  if (isOS) {
    payload.vms = realVms.map(vm => ({
      name: vm.name, base_image: vm.base_image, flavor: vm.flavor,
    }));
    // Una red privada por enlace VM↔VM (el backend mapea links privados
    // a redes privadas por índice) + red provider si hay nodo internet
    const hasInternet = TD.vms.some(v => v.isInternet);
    const privateLinks = TD.links.filter(l => {
      const a = TD.vms.find(v => v.id === l.vmA);
      const b = TD.vms.find(v => v.id === l.vmB);
      return !a?.isInternet && !b?.isInternet;
    });
    payload.networks = privateLinks.map((l, i) => ({
      name: `${name}-net${i + 1}`,
      cidr: `192.168.${100 + i}.0/24`,
      is_provider: false,
    }));
    if (hasInternet) {
      payload.networks.push({ name: TD_INTERNET_NAME, cidr: null, is_provider: true });
    }
  } else {
    payload.vms = realVms.map(vm => ({
      name: vm.name, base_image: vm.base_image, flavor_id: vm.flavor_id,
    }));
  }

  if (mode === 'update')      { tdSendUpdate(payload); return; }
  if (mode === 'new')         { tdPromptSaveAsNew(payload); return; }
  tdSend(payload);
}

function tdPrimaryButtonLabel() {
  return TD.editingSliceId ? 'Guardar cambios' : tdSubmitLabel();
}

async function tdSend(payload) {
  const btn = document.getElementById('btn-td-submit');
  if (btn) { btn.disabled = true; btn.textContent = 'Enviando...'; }
  try {
    await api('POST', '/slices/', payload);
    const successMsg = tdIsAdmin() ? 'Slice guardado como Borrador' : 'Slice enviado para aprobación';
    toast(successMsg, 'success');
    if (TD.animFrame) cancelAnimationFrame(TD.animFrame);
    navigate(state.user.role === 'STUDENT' ? 'my-slices' : 'all-slices');
  } catch (e) {
    toast(e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = tdPrimaryButtonLabel(); }
  }
}

// Guarda los cambios sobre el mismo Borrador que se está editando (PUT).
async function tdSendUpdate(payload) {
  const btn = document.getElementById('btn-td-submit');
  if (btn) { btn.disabled = true; btn.textContent = 'Guardando...'; }
  try {
    await api('PUT', `/slices/${TD.editingSliceId}`, payload);
    toast('Cambios guardados', 'success');
    if (TD.animFrame) cancelAnimationFrame(TD.animFrame);
    navigate('all-slices');
  } catch (e) {
    toast(e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Guardar cambios'; }
  }
}

// Pide un nombre nuevo y crea un Borrador independiente con la topología editada,
// sin tocar el Borrador original.
function tdPromptSaveAsNew(payload) {
  TD._pendingNewPayload = payload;
  openModal('Guardar como nueva topología', `
    <div class="field">
      <label>Nombre de la nueva topología</label>
      <input type="text" id="td-new-name" value="${esc(payload.name + '_copy')}" />
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
      <button class="btn btn-ghost btn-sm" onclick="closeModal()">Cancelar</button>
      <button class="btn btn-primary btn-sm" onclick="tdConfirmSaveAsNew()">Guardar</button>
    </div>
  `);
}

async function tdConfirmSaveAsNew() {
  const name = document.getElementById('td-new-name')?.value?.trim();
  if (!name) { toast('Ingresa un nombre', 'error'); return; }
  const payload = { ...TD._pendingNewPayload, name };
  closeModal();
  await tdSend(payload);
}
