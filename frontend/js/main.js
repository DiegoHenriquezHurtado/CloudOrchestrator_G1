// ── Arranque de la aplicación ─────────────────────────────────

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

// Auto-login si hay token guardado
if (state.token && state.user) {
  showApp();
} else {
  showLogin();
}
