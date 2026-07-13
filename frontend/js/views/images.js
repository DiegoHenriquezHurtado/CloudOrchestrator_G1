// ── Imágenes base (SYSTEM_ADMIN, solo lectura) ────────────────
// El Image Manager actual solo expone GET /images/ y validación;
// las imágenes se colocan directamente en /mnt/storage/base/ del NFS.

async function renderImages() {
  const seq = beginRender();
  const content = document.getElementById('content');
  content.innerHTML = `<div class="text-muted">Cargando...</div>`;
  try {
    const data = await api('GET', '/images/');
    if (isStale(seq)) return;
    const images = data.images || [];

    content.innerHTML = `
      <div class="card">
        <div class="card-title">
          Imágenes base disponibles
          <span class="text-muted text-sm" style="font-weight:400;margin-left:8px">${images.length} imagen${images.length !== 1 ? 'es' : ''}</span>
        </div>
        <p class="text-muted text-sm" style="margin:-4px 0 10px">
          Las imágenes <strong>.qcow2</strong> se gestionan directamente en el almacenamiento compartido
          (<code>/mnt/storage/base/</code>). Este listado refleja lo que ven los workers.
        </p>
        ${images.length === 0
          ? `<div class="empty-state">
               <div class="empty-icon">💿</div>
               <p>No hay imágenes base. Copia archivos .qcow2 al directorio compartido.</p>
             </div>`
          : `<div class="table-wrap"><table>
               <thead>
                 <tr><th>Nombre</th><th>Tamaño</th><th>Ruta en workers</th></tr>
               </thead>
               <tbody>
                 ${images.map(img => `
                   <tr>
                     <td><strong class="mono">${esc(img.name)}</strong></td>
                     <td class="text-muted">${img.size_mb} MB</td>
                     <td class="mono text-muted text-sm">${esc(img.path)}</td>
                   </tr>`).join('')}
               </tbody>
             </table></div>`}
      </div>`;
  } catch (e) {
    if (isStale(seq)) return;
    content.innerHTML = `<div class="card"><p class="error-msg">${esc(e.message)}</p></div>`;
  }
}
