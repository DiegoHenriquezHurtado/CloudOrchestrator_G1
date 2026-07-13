// ── Navegación por rol + router de vistas ─────────────────────
// Refleja las rutas y ROLE_RULES reales del API Gateway:
//   slices/flavors/images → STUDENT, SLICE_ADMIN, SYSTEM_ADMIN
//   infra/networking/placement → SYSTEM_ADMIN

function navItems(role) {
  const icon = {
    dashboard: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
    slices:    `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>`,
    new:       `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>`,
    pending:   `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    network:   `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><line x1="12" y1="8" x2="5.5" y2="16.5"/><line x1="12" y1="8" x2="18.5" y2="16.5"/></svg>`,
    infra:     `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="4" rx="1"/><rect x="2" y="10" width="20" height="4" rx="1"/><rect x="2" y="17" width="20" height="4" rx="1"/></svg>`,
    images:    `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"/><path d="M16 6V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>`,
    flavors:   `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3 6 6 1-4.5 4.5 1 6.5-5.5-3-5.5 3 1-6.5L3 9l6-1z"/></svg>`,
    users:     `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="16" y1="11" x2="22" y2="11"/></svg>`,
  };

  const all = {
    STUDENT: [
      { id: 'overview',    label: 'Dashboard',        icon: icon.dashboard },
      { id: 'my-slices',   label: 'Mis Slices',       icon: icon.slices    },
      { id: 'new-slice',   label: 'Solicitar Slice',  icon: icon.new       },
    ],
    SLICE_ADMIN: [
      { id: 'overview',    label: 'Dashboard',        icon: icon.dashboard },
      { id: 'pending',     label: 'Pendientes',       icon: icon.pending   },
      { id: 'all-slices',  label: 'Todos los Slices', icon: icon.slices    },
      { id: 'new-slice',   label: 'Crear Slice',      icon: icon.new       },
      { id: 'users',       label: 'Usuarios',         icon: icon.users     },
    ],
    SYSTEM_ADMIN: [
      { id: 'overview',    label: 'Dashboard',        icon: icon.dashboard },
      { id: 'all-slices',  label: 'Todos los Slices', icon: icon.slices    },
      { id: 'new-slice',   label: 'Crear Slice',      icon: icon.new       },
      { id: 'infra',       label: 'Infraestructura',  icon: icon.infra     },
      { id: 'images',      label: 'Imágenes',         icon: icon.images    },
      { id: 'networking',  label: 'Redes & VLANs',    icon: icon.network   },
      { id: 'users',       label: 'Usuarios',         icon: icon.users     },
    ],
  };
  return all[role] || [];
}

function navigate(viewId) {
  state.view = viewId;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === viewId);
  });

  const titles = {
    'overview':   'Dashboard',
    'my-slices':  'Mis Slices',
    'new-slice':  'Diseñar Slice',
    'pending':    'Solicitudes Pendientes',
    'all-slices': 'Todos los Slices',
    'infra':      'Infraestructura',
    'images':     'Imágenes Base',
    'networking': 'Redes & VLANs',
    'users':      'Gestión de Usuarios',
  };
  document.getElementById('topbar-title').textContent = titles[viewId] || viewId;

  const render = {
    'overview':   renderOverview,
    'my-slices':  renderMySlices,
    'new-slice':  renderNewSlice,
    'pending':    renderPending,
    'all-slices': renderAllSlices,
    'infra':      renderInfra,
    'images':     renderImages,
    'networking': renderNetworking,
    'users':      renderUsers,
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

  const nav = document.getElementById('sidebar-nav');
  nav.innerHTML = navItems(u.role).map(item => `
    <button class="nav-item" data-view="${item.id}" onclick="navigate('${item.id}')">
      ${item.icon}<span>${item.label}</span>
    </button>
  `).join('');

  navigate(navItems(u.role)[0].id);
}
