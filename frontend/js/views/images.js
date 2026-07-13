// ── Gestión de Imágenes de Sistema (SYSTEM_ADMIN) ──────────────
// Permite cargar imágenes de disco (.img/.qcow2) e importarlas de forma
// independiente de la plataforma de origen, registrándolas en Glance
// (OpenStack) vía el openstack-driver: GET/POST /openstack/images,
// DELETE /openstack/images/{id}.

function fmtSize(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
}

async function renderImages() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const data = await api('GET', '/openstack/images');
    if (isStale(seq)) return;
    const images = data.images || [];

    content.innerHTML = `
      <div class="card">
        <div class="card-title">
          <span>Imágenes registradas
            <span class="text-muted text-sm" style="font-weight:400;margin-left:8px">${images.length} imagen${images.length !== 1 ? 'es' : ''}</span>
          </span>
          <button class="btn btn-primary btn-sm" onclick="openUploadImageModal()">Cargar Nueva Imagen</button>
        </div>
        ${images.length === 0
          ? `<div class="empty-state">
               <div class="empty-icon">💿</div>
               <p>No hay imágenes registradas. Carga una imagen .img o .qcow2 para empezar.</p>
             </div>`
          : `<div class="table-wrap"><table>
               <thead>
                 <tr><th>Nombre</th><th>Formato de Disco</th><th>Visibilidad</th><th>Tamaño</th><th>Acciones</th></tr>
               </thead>
               <tbody>
                 ${images.map(img => `
                   <tr>
                     <td><strong class="mono">${esc(img.name || '(sin nombre)')}</strong></td>
                     <td class="text-muted">${esc((img.disk_format || '—').toUpperCase())}</td>
                     <td>${esc(img.visibility || '—')}</td>
                     <td class="text-muted">${fmtSize(img.size)}</td>
                     <td><button class="btn btn-danger btn-sm" onclick="deleteImage('${img.id}', '${esc(img.name || img.id)}')">Eliminar</button></td>
                   </tr>`).join('')}
               </tbody>
             </table></div>`}
      </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}

function openUploadImageModal() {
  openModal('Cargar Nueva Imagen', `
    <div class="field">
      <label>Nombre de la Imagen</label>
      <input type="text" id="img-name" placeholder="ej. ubuntu-24.04-minimal" autocomplete="off" />
    </div>
    <div class="field">
      <label>Archivo de Imagen (.img / .qcow2)</label>
      <input type="file" id="img-file" accept=".img,.qcow2" />
    </div>
    <div class="field-row">
      <div class="field">
        <label>Formato de Disco</label>
        <select id="img-disk-format">
          <option value="qcow2" selected>QCOW2</option>
        </select>
      </div>
      <div class="field">
        <label>Formato de Contenedor</label>
        <select id="img-container-format">
          <option value="bare" selected>Bare</option>
        </select>
      </div>
    </div>
    <div class="field flex items-center gap-1">
      <input type="checkbox" id="img-visibility" checked style="width:auto" />
      <label for="img-visibility" style="margin:0">Pública</label>
    </div>
    <div id="img-upload-progress" class="hidden mt-1">
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;height:8px">
        <div id="img-upload-progress-bar" style="background:var(--primary-dark);height:100%;width:0%;transition:width .15s"></div>
      </div>
      <p class="text-muted text-sm mt-1" id="img-upload-progress-label">Subiendo... 0%</p>
    </div>
    <button class="btn btn-primary btn-full mt-2" id="img-upload-btn" onclick="uploadImage()">Guardar/Cargar</button>
  `);
}

async function uploadImage() {
  const name = document.getElementById('img-name')?.value?.trim();
  const fileInput = document.getElementById('img-file');
  const file = fileInput?.files?.[0];
  const diskFormat = document.getElementById('img-disk-format')?.value;
  const containerFormat = document.getElementById('img-container-format')?.value;
  const visibility = document.getElementById('img-visibility')?.checked ? 'public' : 'private';

  if (!name) { toast('Indica un nombre para la imagen', 'error'); return; }
  if (!file) { toast('Selecciona un archivo .img o .qcow2', 'error'); return; }
  if (!/\.(img|qcow2)$/i.test(file.name)) { toast('El archivo debe tener extensión .img o .qcow2', 'error'); return; }

  const btn = document.getElementById('img-upload-btn');
  const progressWrap = document.getElementById('img-upload-progress');
  const progressBar = document.getElementById('img-upload-progress-bar');
  const progressLabel = document.getElementById('img-upload-progress-label');

  const formData = new FormData();
  formData.append('name', name);
  formData.append('file', file);
  formData.append('disk_format', diskFormat);
  formData.append('container_format', containerFormat);
  formData.append('visibility', visibility);

  btn.disabled = true;
  btn.textContent = 'Cargando...';
  progressWrap.classList.remove('hidden');

  try {
    await apiUpload('POST', '/openstack/images', formData, pct => {
      progressBar.style.width = `${pct}%`;
      progressLabel.textContent = pct < 100 ? `Subiendo... ${pct}%` : 'Procesando en Glance...';
    });
    toast(`Imagen "${name}" cargada correctamente`, 'success');
    closeModal();
    renderImages();
  } catch (e) {
    toast(e.message, 'error');
    btn.disabled = false;
    btn.textContent = 'Guardar/Cargar';
  }
}

async function deleteImage(id, name) {
  if (!confirm(`¿Eliminar la imagen "${name}"? Esta acción no se puede deshacer.`)) return;
  try {
    await api('DELETE', `/openstack/images/${id}`);
    toast('Imagen eliminada', 'success');
    renderImages();
  } catch (e) {
    toast(e.message, 'error');
  }
}
