// ── Config + estado global + cliente HTTP ─────────────────────
// Cambia esta URL si el gateway corre en otro host/puerto
const API = 'http://localhost:8090/api/v1';

const state = {
  token: localStorage.getItem('co_token') || null,
  user:  JSON.parse(localStorage.getItem('co_user') || 'null'),
  view:  null,
  renderSeq: 0, // invalida renders asíncronos obsoletos (ver beginRender/isStale)
};

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
  if (!res.ok) {
    const detail = typeof data.detail === 'string'
      ? data.detail
      : JSON.stringify(data.detail || `Error ${res.status}`);
    throw new Error(detail);
  }
  return data;
}

// Sube un FormData (ej. carga de archivos) reportando progreso vía XHR,
// ya que fetch no expone eventos de progreso de subida.
function apiUpload(method, path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, `${API}${path}`);
    if (state.token) xhr.setRequestHeader('Authorization', `Bearer ${state.token}`);

    xhr.upload.addEventListener('progress', e => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    });

    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
      } else {
        const detail = typeof data.detail === 'string'
          ? data.detail
          : JSON.stringify(data.detail || `Error ${xhr.status}`);
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error('Error de red al subir el archivo'));
    xhr.send(formData);
  });
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
