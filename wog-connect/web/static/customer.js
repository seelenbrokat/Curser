function formatApiError(data, fallback) {
  const detail = data?.detail ?? data?.error;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'string' ? d : d?.msg || d?.message || JSON.stringify(d)))
      .filter(Boolean)
      .join('; ');
  }
  if (detail && typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail);
  }
  return fallback || 'Fehler';
}

async function api(url, opts = {}) {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (res.status === 401) {
    location.href = '/login';
    throw new Error('Login required');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatApiError(data, res.statusText || 'Fehler'));
  }
  return data;
}

function showMsg(text, kind = 'info') {
  const el = document.getElementById('msg');
  el.className = `status-msg ${kind}`;
  el.textContent = text;
  el.classList.remove('hidden');
}

function hideMsg() {
  document.getElementById('msg').classList.add('hidden');
}

function statusLabel(s) {
  const map = {
    uploaded: 'Erfasst',
    label_created: 'Label erstellt',
    handed_over: 'Übergeben',
    delivered: 'Zugestellt',
    error: 'Fehler',
  };
  return map[s] || s || '—';
}

async function loadMe() {
  const me = await api('/api/auth/me');
  if (me.role !== 'customer') {
    location.href = '/';
    return me;
  }
  const name = me.display_name || me.user;
  document.getElementById('customerBrand').textContent = name;
  if (me.sender) {
    const s = me.sender;
    document.getElementById('senderHint').textContent =
      `Absender: ${s.name1}, ${s.street}, ${s.zip_code} ${s.city} (${s.country || 'CH'})`;
  }
  return me;
}

async function loadProducts() {
  const data = await api('/api/v1/delivery-products');
  const sel = document.getElementById('delivery');
  const groups = {};
  for (const p of data.products || []) {
    (groups[p.group || 'Sonstiges'] ||= []).push(p);
  }
  sel.innerHTML = Object.keys(groups)
    .map((g) => {
      const opts = groups[g].map((p) => `<option value="${p.id}">${p.label}</option>`).join('');
      return `<optgroup label="${g}">${opts}</optgroup>`;
    })
    .join('');
  sel.value = data.default || 'eco';
}

async function loadList() {
  const data = await api('/api/v1/customer/shipments?limit=40');
  const box = document.getElementById('list');
  const rows = data.shipments || [];
  if (!rows.length) {
    box.innerHTML = '<p class="hint">Noch keine Sendungen erfasst.</p>';
    return;
  }
  box.innerHTML = rows
    .map((s) => {
      const when = String(s.created_at || '').slice(0, 16).replace('T', ' ');
      const labelBtn = s.label_path
        ? `<a href="/api/v1/shipments/${s.id}/label" target="_blank"><button type="button" class="primary sm">Label öffnen</button></a>`
        : `<button type="button" class="secondary sm" data-relabel="${s.id}">Label erzeugen</button>`;
      return `<div class="shipment-card">
        <div class="shipment-main">
          <div class="shipment-title">${s.recipient_name || '—'} · ${s.recipient_zip || ''} ${s.recipient_city || ''}</div>
          <div class="shipment-meta">
            <div class="meta-item"><span class="meta-label">Status</span><span class="meta-value">${statusLabel(s.status)}</span></div>
            <div class="meta-item"><span class="meta-label">Identcode</span><span class="meta-value">${s.identcode || '—'}</span></div>
            <div class="meta-item"><span class="meta-label">Referenz</span><span class="meta-value">${s.sendungsnummer || '—'}</span></div>
            <div class="meta-item"><span class="meta-label">Erfasst</span><span class="meta-value">${when || '—'}</span></div>
          </div>
          ${s.error_message ? `<div class="status-msg error">${s.error_message}</div>` : ''}
        </div>
        <div class="shipment-actions">${labelBtn}</div>
      </div>`;
    })
    .join('');

  box.querySelectorAll('[data-relabel]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const res = await api(`/api/v1/shipments/${btn.dataset.relabel}/generate-label`, { method: 'POST' });
        if (!res.ok) throw new Error(res.error || 'Label fehlgeschlagen');
        window.open(`/api/v1/shipments/${btn.dataset.relabel}/label`, '_blank');
        await loadList();
      } catch (e) {
        showMsg(e.message || String(e), 'error');
      } finally {
        btn.disabled = false;
      }
    });
  });
}

document.getElementById('createForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideMsg();
  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.textContent = 'Label wird erzeugt…';
  try {
    const payload = {
      recipient: {
        name1: document.getElementById('name1').value.trim(),
        name2: document.getElementById('name2').value.trim(),
        street: document.getElementById('street').value.trim(),
        zip_code: document.getElementById('zip').value.trim(),
        city: document.getElementById('city').value.trim(),
        country: (document.getElementById('country').value.trim() || 'CH').toUpperCase(),
        email: document.getElementById('email').value.trim(),
      },
      reference: document.getElementById('reference').value.trim(),
      delivery_product_id: document.getElementById('delivery').value,
      weight_grams: Number(document.getElementById('weight').value || 1000),
      packstuecke: Number(document.getElementById('packs').value || 1),
      generate_label: true,
    };
    const res = await api('/api/v1/customer/shipments', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(res.error || res.detail || 'Label fehlgeschlagen');
    }
    const id = res.shipmentId || res.shipment_id;
    showMsg(`Label erstellt${res.identcode ? ` · ${res.identcode}` : ''}`, 'success');
    if (id) window.open(`/api/v1/shipments/${id}/label`, '_blank');
    document.getElementById('createForm').reset();
    document.getElementById('country').value = 'CH';
    document.getElementById('weight').value = '1000';
    document.getElementById('packs').value = '1';
    await loadProducts();
    await loadList();
  } catch (err) {
    showMsg(err.message || String(err), 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Label erzeugen & drucken';
  }
});

document.getElementById('logoutBtn').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' });
  location.href = '/login';
});

Promise.all([loadMe(), loadProducts(), loadList()]).catch(() => {
  location.href = '/login';
});
