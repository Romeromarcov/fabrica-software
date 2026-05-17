/* Fábrica de Software — Omni ERP — app.js */

// ── Toast ─────────────────────────────────────────────────────────────────────
window._showToast = function(msg, variant = "success") {
  const toastEl = document.getElementById("liveToast");
  const msgEl   = document.getElementById("toastMsg");
  if (!toastEl || !msgEl) return;
  msgEl.textContent = msg;
  toastEl.className = `toast align-items-center border-0 text-bg-${variant}`;
  bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 3500 }).show();
};

// ── Sidebar active link ───────────────────────────────────────────────────────
(function() {
  const path = window.location.pathname;
  document.querySelectorAll(".sidebar nav a").forEach(a => {
    const href = a.getAttribute("href");
    if (href === "/" && path === "/") a.classList.add("active");
    else if (href !== "/" && path.startsWith(href)) a.classList.add("active");
  });
})();

// ── Poll feature status (used in feature_detail when SSE is active) ───────────
window._pollStatus = function(featureId, intervalMs = 5000) {
  return setInterval(async () => {
    try {
      const res  = await fetch(`/api/feature/${featureId}/status`);
      const data = await res.json();
      const badge = document.getElementById("statusBadge");
      if (badge) {
        badge.textContent = data.status || "?";
        badge.className = `badge badge-status-${data.status} rounded-pill px-2`;
      }
    } catch (_) { /* ignore network blips */ }
  }, intervalMs);
};

// ── Format numbers ────────────────────────────────────────────────────────────
window._fmtUSD = v => "$" + Number(v).toFixed(4);
