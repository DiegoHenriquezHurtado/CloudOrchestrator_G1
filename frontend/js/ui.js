// ── Componentes UI compartidos: toast, modal, badge ───────────

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-dot"></span>${msg}`;
  document.getElementById('toast-container').appendChild(el);
  // Los errores traen razones largas: más tiempo en pantalla
  setTimeout(() => el.remove(), type === 'error' ? 7000 : 3500);
}

function openModal(title, html) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = html;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  document.getElementById('modal-body').innerHTML = '';
}

function badge(status) {
  const map = {
    ACTIVE:           'badge-active',
    READY:            'badge-active',
    ALIVE:            'badge-active',
    DRAFT:            'badge-info',
    PENDING_APPROVAL: 'badge-pending',
    PENDING:          'badge-pending',
    PLACEMENT_READY:  'badge-pending',
    IN_PROGRESS:      'badge-pending',
    FAILED:           'badge-failed',
    DOWN:             'badge-failed',
    TERMINATING:      'badge-failed',
    REJECTED:         'badge-failed',
    DELETED:          'badge-failed',
  };
  const cls = map[status] || 'badge-info';
  return `<span class="badge ${cls}">${status}</span>`;
}

// ── Guard contra renders obsoletos ────────────────────────────
// Cada vista toma un número de secuencia al iniciar; si el usuario navega
// antes de que termine su fetch, el número cambia y la vista vieja no debe
// escribir sobre la nueva. Uso: const seq = beginRender();
// ... await ...; if (isStale(seq)) return;
function beginRender() { return ++state.renderSeq; }
function isStale(seq)  { return seq !== state.renderSeq; }

// Escape básico para valores que vienen del backend/inputs
function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
