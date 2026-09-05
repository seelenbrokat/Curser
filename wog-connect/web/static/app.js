let shipments = [];
let filter = 'pending';
let deliveryProducts = [];
let queryTour = '';
let queryDate = todayISO();
let querySearch = '';

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function activateTab(name) {
  document.querySelectorAll('.tab').forEach((b) => {
    b.classList.toggle('active', b.dataset.filter === name);
  });
  filter = name;
}
let bulkRunning = false;
let lastAddressSuggestion = null;

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: 'same-origin', ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  return data;
}

function statusLabel(s) {
  const map = {
    uploaded: 'Bereit',
    label_created: 'Label erstellt',
    handed_over: 'An Post übergeben',
    delivered: 'Zugestellt',
    error: 'Fehler',
  };
  return map[s] || s;
}

function needsLabel(s) {
  return ['uploaded', 'error'].includes(s.status) || !s.identcode;
}

function deliveryLabel(id) {
  const p = deliveryProducts.find((x) => x.id === id);
  return p ? p.label : id || '—';
}

function formatWeight(grams) {
  if (!grams) return '—';
  if (grams >= 1000) return `${(grams / 1000).toFixed(2).replace(/\.00$/, '')} kg`;
  return `${grams} g`;
}

const POST_MAX_WEIGHT_GRAMS = 30000;

function weightWarningFor(grams, pieces = 1) {
  const n = Math.max(1, parseInt(pieces, 10) || 1);
  const total = Math.max(0, parseInt(grams, 10) || 0);
  const perPiece = n > 1 ? Math.max(1, Math.floor(total / n)) : total;
  if (perPiece <= POST_MAX_WEIGHT_GRAMS) return null;
  const kg = (perPiece / 1000).toFixed(1);
  if (n > 1) {
    return `Gewicht ${kg} kg pro Packstück überschreitet das Post-Maximum (30 kg). Bitte aufteilen oder reduzieren.`;
  }
  return `Gewicht ${kg} kg überschreitet das Post-Maximum (30 kg). Bitte aufteilen oder reduzieren.`;
}

function weightBadge(s) {
  const warn = s.weight_warning || weightWarningFor(s.weight_grams, s.packstuecke);
  if (!warn) return '';
  return `<span class="badge weight-warn" title="${warn.replace(/"/g, '&quot;')}">Gewicht zu hoch</span>`;
}

function formatCarrierRef(ref) {
  if (!ref) return '';
  if (ref.toUpperCase() === 'DPD') return 'Post';
  return ref;
}

function formatTourDate(s) {
  const raw = s.tour_planned_date || s.tour_uploaded_at || s.created_at;
  if (!raw) return '';
  return raw.slice(0, 10);
}

function shipmentHasPdf(s) {
  if (!s.label_path) return false;
  return (s.label_format || '').toLowerCase() === 'pdf' || String(s.label_path).toLowerCase().endsWith('.pdf');
}

function soloplanMeta(s) {
  const parts = [];
  if (s.sendungsnummer) parts.push(`Sendung ${s.sendungsnummer}`);
  if (s.tour_number) parts.push(`Tour ${s.tour_number}`);
  if (s.transport_order_number) parts.push(`TA ${s.transport_order_number}`);
  if (s.item_number) parts.push(`Pos ${s.item_number}`);
  return parts.join(' · ') || '—';
}

function billingBadge(s) {
  if (!s.billing_total_chf || s.billing_total_chf === '—') return '';
  const cls = s.billing_surcharge_hint ? 'billing-warn' : 'billing';
  const title = (s.billing_products || []).join(', ');
  return `<span class="badge ${cls}" title="${title.replace(/"/g, '&quot;')}">CHF ${s.billing_total_chf}</span>`;
}

function addressBadge(s) {
  if (s.address_valid === true) {
    const quality = s.address_quality ? ` (${s.address_quality})` : '';
    const title = `${s.address_message || 'Von Post bestätigt'}${quality}`;
    return `<span class="badge address-ok" title="${title.replace(/"/g, '&quot;')}">Adresse OK</span>`;
  }
  if (s.address_valid === false) {
    const title = (s.address_message || 'Adresse ungültig').replace(/"/g, '&quot;');
    return `<span class="badge address-bad" title="${title}">Adresse ungültig</span>`;
  }
  if (queryTour) {
    return '<span class="badge address-unknown" title="Noch nicht geprüft – „Adressen prüfen“ klicken">Adresse offen</span>';
  }
  return '';
}

function renderKpis(rows) {
  document.getElementById('kpiOpen').textContent = rows.filter((r) => ['uploaded', 'label_created', 'handed_over', 'error'].includes(r.status)).length;
  document.getElementById('kpiLabel').textContent = rows.filter((r) => r.status === 'label_created').length;
  document.getElementById('kpiDone').textContent = rows.filter((r) => r.status === 'delivered').length;
  document.getElementById('kpiErr').textContent = rows.filter((r) => r.status === 'error').length;
}

function isTrackable(s) {
  return !!s.identcode && ['label_created', 'handed_over'].includes(s.status);
}

function canDeliveryProof(s) {
  return !!(s.identcode && (s.status === 'delivered' || s.tracking_delivered || s.delivery_proof_available));
}

function filtered() {
  if (filter === 'pending') return shipments.filter(needsLabel);
  if (filter === 'tracking') return shipments.filter(isTrackable);
  if (filter === 'open') return shipments.filter((s) => ['uploaded', 'label_created', 'handed_over', 'error'].includes(s.status));
  if (filter === 'delivered') return shipments.filter((s) => s.status === 'delivered');
  return shipments;
}

function setProgress(current, total, text) {
  const box = document.getElementById('labelProgress');
  const bar = document.getElementById('labelProgressBar');
  const label = document.getElementById('labelProgressText');
  if (total <= 0) {
    box.classList.add('hidden');
    return;
  }
  box.classList.remove('hidden');
  const pct = Math.round((current / total) * 100);
  bar.style.setProperty('--pct', `${pct}%`);
  label.textContent = text || `${current} / ${total}`;
}

function setStatusMsg(el, text, type = 'info') {
  if (!el) return;
  el.classList.remove('hidden', 'ok', 'err', 'info', 'warn');
  el.classList.add('status-msg', type);
  el.textContent = text;
  el.title = '';
}

function setEditMsg(text, type = 'info') {
  const msg = document.getElementById('editMsg');
  msg.classList.remove('hidden', 'msg-ok', 'msg-err', 'msg-warn');
  msg.textContent = text;
  if (type === 'ok') msg.classList.add('msg-ok');
  if (type === 'err') msg.classList.add('msg-err');
  if (type === 'warn') msg.classList.add('msg-warn');
}

function refreshEditWeightWarning() {
  const grams = parseInt(document.getElementById('editWeight').value, 10) || 0;
  const pieces = parseInt(document.getElementById('editPackstuecke').value, 10) || 1;
  const warn = weightWarningFor(grams, pieces);
  const box = document.getElementById('editWeightWarn');
  if (!box) return;
  if (warn) {
    box.textContent = `⚠ ${warn}`;
    box.classList.remove('hidden');
  } else {
    box.textContent = '';
    box.classList.add('hidden');
  }
}

function renderList() {
  const list = document.getElementById('list');
  const rows = filtered();
  list.innerHTML = '';
  if (!rows.length) {
    let hint = 'Keine Sendungen in der gewählten Ansicht.';
    if (queryTour) {
      hint = 'Keine Sendungen für diese Tour in der gewählten Ansicht.';
    } else if (filter === 'pending') {
      hint = queryDate
        ? `Keine Sendungen ohne Label für ${queryDate} – alle erledigt oder noch keine Touren importiert.`
        : 'Keine Sendungen ohne Label – alle erledigt oder noch keine Touren importiert.';
    } else if (filter === 'tracking') {
      hint = 'Keine Sendungen unterwegs – Label erstellt oder an Post übergeben mit Identcode.';
    }
    list.innerHTML = `
      <div class="empty-state">
        <h3>Keine Sendungen</h3>
        <p>${hint}</p>
      </div>`;
    return;
  }
  for (const s of rows) {
    const div = document.createElement('div');
    div.className = 'row';
    const addr = [s.recipient_street, s.recipient_zip, s.recipient_city].filter(Boolean).join(' · ');
    const labelBtn = s.label_path
      ? `<a href="/api/v1/shipments/${s.id}/label" target="_blank"><button type="button" class="secondary sm">${(s.label_format || '').toLowerCase() === 'pdf' ? 'PDF öffnen' : 'Label öffnen'}</button></a>`
      : `<button type="button" class="label-btn sm" data-label="${s.id}">Label erzeugen</button>`;
    div.innerHTML = `
      <div class="row-head">
        <div>
          <h3>${s.recipient_name || '—'}${s.recipient_name2 ? ` <span class="row-city">· ${s.recipient_name2}</span>` : ''}</h3>
          <div class="sub">${addr || '—'}</div>
        </div>
        <div class="row-badges">
          <span class="badge ${s.status}">${statusLabel(s.status)}</span>
          ${s.tracking_summary ? `<span class="badge tracking" title="${(s.tracking_synced_at || '').replace(/"/g, '&quot;')}">${s.tracking_summary}</span>` : ''}
          ${addressBadge(s)}
          ${weightBadge(s)}
          ${billingBadge(s)}
        </div>
      </div>
      <div class="row-meta">
        <div class="meta-item"><span class="meta-label">Soloplan</span><span class="meta-value">${soloplanMeta(s)}</span></div>
        <div class="meta-item"><span class="meta-label">Tour-Datum</span><span class="meta-value">${formatTourDate(s) || '—'}</span></div>
        <div class="meta-item"><span class="meta-label">Zustellart</span><span class="meta-value delivery-tag">${deliveryLabel(s.delivery_product_id)}</span></div>
        <div class="meta-item"><span class="meta-label">Gewicht / Packstücke</span><span class="meta-value${s.weight_warning || weightWarningFor(s.weight_grams, s.packstuecke) ? ' weight-hot' : ''}">${formatWeight(s.weight_grams)} · ${s.packstuecke || 1} Stk.${s.weight_warning || weightWarningFor(s.weight_grams, s.packstuecke) ? ' ⚠' : ''}</span></div>
        <div class="meta-item"><span class="meta-label">Identcode</span><span class="meta-value">${s.identcode || '—'}${s.label_count > 1 ? ` (${s.label_count} Labels)` : ''}</span></div>
        ${s.tracking_synced_at ? `<div class="meta-item"><span class="meta-label">Tracking-Sync</span><span class="meta-value">${String(s.tracking_synced_at).slice(0, 16).replace('T', ' ')}</span></div>` : ''}
      </div>
      ${s.recipient_email ? `<div class="sub">${s.recipient_email}${s.notify_recipient ? ' · E-Mail-Benachrichtigung aktiv' : ''}</div>` : ''}
      ${s.billing_total_chf && s.billing_total_chf !== '—' ? `<div class="sub billing-line">Post verrechnet: CHF ${s.billing_total_chf}${s.billing_products?.length ? ` · ${s.billing_products.join(', ')}` : ''}${s.billing_surcharge_hint ? ' · Hinweis auf Mehrkosten/Sperrgut' : ''}</div>` : ''}
      ${s.error_message ? `<div class="row-error">${s.error_message}</div>` : ''}
      <div class="actions">
        ${labelBtn}
        ${s.tracking_url ? `<a class="btn secondary sm" href="${s.tracking_url}" target="_blank" rel="noopener">Sendung verfolgen</a>` : ''}
        ${s.identcode ? `<button type="button" class="secondary sm" data-tracking="${s.id}">Tracking aktualisieren</button>` : ''}
        ${canDeliveryProof(s)
          ? `<a href="/api/v1/shipments/${s.id}/delivery-proof" target="_blank"><button type="button" class="primary sm">Ablieferbeleg</button></a>`
          : (s.identcode ? `<button type="button" class="secondary sm" data-proof="${s.id}" title="Nach Zustellung per Post-Tracking verfügbar">Ablieferbeleg</button>` : '')}
        <button type="button" class="secondary sm" data-edit="${s.id}">Bearbeiten</button>
        ${s.status !== 'handed_over' && s.status !== 'delivered' ? `<button type="button" class="secondary sm" data-action="handed_over" data-id="${s.id}">An Post übergeben</button>` : ''}
        ${s.status !== 'delivered' ? `<button type="button" class="secondary sm" data-action="delivered" data-id="${s.id}">Zugestellt</button>` : ''}
      </div>
      <div class="tracking-box hidden" id="tracking-${s.id}"></div>`;
    list.appendChild(div);
  }

  list.querySelectorAll('[data-edit]').forEach((btn) => btn.addEventListener('click', () => openEdit(btn.dataset.edit)));
  list.querySelectorAll('[data-label]').forEach((btn) => btn.addEventListener('click', () => generateLabel(btn.dataset.label)));
  list.querySelectorAll('[data-tracking]').forEach((btn) => btn.addEventListener('click', () => refreshTracking(btn.dataset.tracking)));
  list.querySelectorAll('[data-proof]').forEach((btn) => btn.addEventListener('click', () => requestDeliveryProof(btn.dataset.proof)));
  list.querySelectorAll('button[data-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await api(`/api/v1/shipments/${btn.dataset.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: btn.dataset.action }),
      });
      await load();
    });
  });
}

async function requestDeliveryProof(id) {
  const box = document.getElementById(`tracking-${id}`);
  if (box) {
    box.classList.remove('hidden');
    box.textContent = 'Tracking prüfen für Ablieferbeleg …';
  }
  try {
    const data = await api(`/api/v1/shipments/${id}/tracking/refresh`, { method: 'POST' });
    if (data.delivered || data.deliveryProofAvailable) {
      window.open(`/api/v1/shipments/${id}/delivery-proof`, '_blank');
      await load();
      return;
    }
    if (box) {
      box.innerHTML = `<span class="muted">Ablieferbeleg erst nach Zustellung verfügbar${data.summary ? ` · Aktuell: ${data.summary}` : ''}.</span>`;
    }
    await load();
  } catch (e) {
    if (box) box.innerHTML = `<span class="msg-err">${e.message}</span>`;
  }
}

async function refreshTracking(id) {
  const box = document.getElementById(`tracking-${id}`);
  if (!box) return;
  box.classList.remove('hidden');
  box.textContent = 'Tracking wird geladen …';
  try {
    const data = await api(`/api/v1/shipments/${id}/tracking/refresh`, { method: 'POST' });
    const summary = data.summary
      || (data.globalStatus === 'REPORTED' ? 'Elektronisch gemeldet' : '')
      || '';
    // Echtes Fehler nur wenn Post nichts liefert und keine Status-Zusammenfassung da ist
    if (data.error && !data.events?.length && !summary) {
      box.innerHTML = `<span class="msg-err">Tracking: ${data.error}</span>`;
      return;
    }
    const parts = [];
    if (summary) parts.push(`<strong>Aktuell:</strong> ${summary}`);
    if (data.trackingUrl) {
      parts.push(`<a href="${data.trackingUrl}" target="_blank">Bei der Post öffnen</a>`);
    }
    if (data.events?.length) {
      parts.push('<ul class="tracking-events">' + data.events.map((ev) =>
        `<li><span class="ev-at">${ev.at || ''}</span><span class="ev-title">${ev.title || ''}</span>${ev.detail ? `<br>${ev.detail}` : ''}</li>`
      ).join('') + '</ul>');
    } else if (summary) {
      parts.push('<span class="muted">Noch keine weiteren Scan-Events – Sendung ist bei der Post elektronisch bekannt.</span>');
    } else {
      parts.push('<span class="muted">Noch keine Tracking-Events verfügbar.</span>');
    }
    if (data.error && summary) {
      parts.push(`<span class="muted">Hinweis: ${data.error}</span>`);
    }
    box.innerHTML = parts.join('<br>');
    await load();
  } catch (e) {
    box.innerHTML = `<span class="msg-err">${e.message}</span>`;
  }
}

async function loadProducts() {
  const data = await api('/api/v1/delivery-products');
  deliveryProducts = data.products || [];
  const sel = document.getElementById('editDelivery');
  const groups = {};
  deliveryProducts.forEach((p) => {
    const g = p.group || 'Sonstiges';
    if (!groups[g]) groups[g] = [];
    groups[g].push(p);
  });
  // Standard-Gruppe zuerst, Unterschrift nicht als Default
  const order = ['Standard', 'Express', 'Zeitfenster', 'Zusatz', 'Unterschrift'];
  const keys = [...order.filter((k) => groups[k]), ...Object.keys(groups).filter((k) => !order.includes(k))];
  sel.innerHTML = keys.map((g) => {
    const opts = groups[g].map((p) => `<option value="${p.id}">${p.label}</option>`).join('');
    return `<optgroup label="${g}">${opts}</optgroup>`;
  }).join('');
  sel.value = data.default || 'eco';
  sel.addEventListener('change', updateDeliveryHint);
  updateDeliveryHint();
}

function updateDeliveryHint() {
  const hint = document.getElementById('editDeliveryHint');
  if (!hint) return;
  const id = document.getElementById('editDelivery')?.value;
  const p = deliveryProducts.find((x) => x.id === id);
  hint.textContent = p?.description || 'Standard: Priority ohne Unterschrift.';
}

async function loadFaq() {
  const box = document.getElementById('faqList');
  if (!box) return;
  try {
    const data = await api('/api/v1/faq');
    const items = data.items || [];
    box.innerHTML = items.map((item, i) => `
      <details class="faq-item"${i === 0 ? ' open' : ''}>
        <summary>${item.q}</summary>
        <p>${item.a}</p>
      </details>
    `).join('');
  } catch (e) {
    box.innerHTML = `<p class="msg-err">${e.message}</p>`;
  }
}

async function openEdit(id) {
  const data = await api(`/api/v1/shipments/${id}`);
  const s = data.shipment;
  const d = data.draft?.recipient || {};
  document.getElementById('editId').value = id;
  document.getElementById('editName').value = d.name1 || s.recipient_name || '';
  document.getElementById('editName2').value = d.name2 || s.recipient_name2 || '';
  document.getElementById('editStreet').value = d.street || s.recipient_street || '';
  document.getElementById('editZip').value = d.zip_code || s.recipient_zip || '';
  document.getElementById('editCity').value = d.city || s.recipient_city || '';
  document.getElementById('editCountry').value = d.country || s.recipient_country || 'CH';
  document.getElementById('editEmail').value = d.email || s.recipient_email || '';
  document.getElementById('editNotify').checked = data.draft?.notify_recipient ?? s.notify_recipient ?? Boolean(d.email || s.recipient_email);
  document.getElementById('editDelivery').value = s.delivery_product_id || data.draft?.delivery_product_id || 'eco';
  document.getElementById('editWeight').value = data.draft?.weight_grams || s.weight_grams || 1000;
  document.getElementById('editPackstuecke').value = data.draft?.packstuecke || s.packstuecke || 1;
  const mc = data.draft?.recipient_matchcode || '';
  const bp = data.draft?.recipient_bp_id || '';
  const mcHint = document.getElementById('editMatchcodeHint');
  if (mcHint) {
    mcHint.textContent = mc
      ? `Soloplan-Matchcode: ${mc}${bp ? ` · BP ${bp}` : ''}`
      : 'Soloplan-Matchcode: nicht vorhanden (Speichern unter Name+PLZ)';
  }
  const saveBook = document.getElementById('editSaveAddressBook');
  if (saveBook) saveBook.checked = false;
  document.getElementById('editMsg').classList.add('hidden');
  document.getElementById('applySuggestionBtn').classList.add('hidden');
  document.getElementById('acceptAddressBtn').classList.add('hidden');
  lastAddressSuggestion = null;
  refreshEditWeightWarning();
  document.getElementById('editModal').classList.remove('hidden');
}

function closeEdit() {
  document.getElementById('editModal').classList.add('hidden');
}

function buildPayload() {
  return {
    recipient: {
      name1: document.getElementById('editName').value.trim(),
      name2: document.getElementById('editName2').value.trim() || null,
      street: document.getElementById('editStreet').value.trim(),
      zip_code: document.getElementById('editZip').value.trim(),
      city: document.getElementById('editCity').value.trim(),
      country: document.getElementById('editCountry').value.trim().toUpperCase(),
      email: document.getElementById('editEmail').value.trim() || null,
    },
    delivery_product_id: document.getElementById('editDelivery').value,
    notify_recipient: document.getElementById('editNotify').checked,
    weight_grams: parseInt(document.getElementById('editWeight').value, 10) || 1000,
    packstuecke: parseInt(document.getElementById('editPackstuecke').value, 10) || 1,
    save_to_address_book: Boolean(document.getElementById('editSaveAddressBook')?.checked),
  };
}

async function validateCurrentAddress() {
  const id = document.getElementById('editId').value;
  const applyBtn = document.getElementById('applySuggestionBtn');
  const acceptBtn = document.getElementById('acceptAddressBtn');
  applyBtn.classList.add('hidden');
  acceptBtn.classList.add('hidden');
  lastAddressSuggestion = null;
  setEditMsg('Adresse wird geprüft …');
  try {
    await api(`/api/v1/shipments/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload()),
    });
    const data = await api(`/api/v1/shipments/${id}/validate-address`, { method: 'POST' });
    const quality = data.quality ? ` (${data.quality})` : '';
    setEditMsg(`${data.valid ? '✓' : '✗'} ${data.message}${quality}`, data.valid ? 'ok' : 'err');
    if (data.valid && data.applied) {
      const fresh = await api(`/api/v1/shipments/${id}`);
      const d = fresh.draft?.recipient || {};
      const s = fresh.shipment || {};
      document.getElementById('editName').value = d.name1 || s.recipient_name || '';
      document.getElementById('editName2').value = d.name2 || s.recipient_name2 || '';
      document.getElementById('editStreet').value = d.street || s.recipient_street || '';
      document.getElementById('editZip').value = d.zip_code || s.recipient_zip || '';
      document.getElementById('editCity').value = d.city || s.recipient_city || '';
    }
    if (!data.valid) {
      acceptBtn.classList.remove('hidden');
      if (data.suggested) {
        lastAddressSuggestion = data.suggested;
        applyBtn.classList.remove('hidden');
      }
    }
    await load();
    return data;
  } catch (e) {
    setEditMsg(`Adressprüfung: ${e.message}`, 'err');
    throw e;
  }
}

async function acceptCurrentAddress() {
  const id = document.getElementById('editId').value;
  await api(`/api/v1/shipments/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildPayload()),
  });
  const data = await api(`/api/v1/shipments/${id}/accept-address`, { method: 'POST' });
  setEditMsg(`✓ ${data.message} – Label kann erzeugt werden`, 'ok');
  document.getElementById('acceptAddressBtn').classList.add('hidden');
  document.getElementById('applySuggestionBtn').classList.add('hidden');
  await load();
}

function applyAddressSuggestion() {
  if (!lastAddressSuggestion) return;
  const s = lastAddressSuggestion;
  if (s.name1) document.getElementById('editName').value = s.name1;
  if (s.name2) document.getElementById('editName2').value = s.name2;
  if (s.street) document.getElementById('editStreet').value = s.street;
  if (s.zip_code) document.getElementById('editZip').value = s.zip_code;
  if (s.city) document.getElementById('editCity').value = s.city;
  document.getElementById('applySuggestionBtn').classList.add('hidden');
  lastAddressSuggestion = null;
}

function applyAddressResults(data) {
  const map = Object.fromEntries((data.results || []).map((r) => [r.shipmentId, r]));
  shipments = shipments.map((s) => {
    const r = map[s.id];
    if (!r) return s;
    return {
      ...s,
      address_valid: r.valid,
      address_message: r.message,
      address_quality: r.quality,
    };
  });
}

async function validateTourAddresses() {
  if (!queryTour) return;
  const msg = document.getElementById('bulkMsg');
  setStatusMsg(msg, 'Adressen werden geprüft …', 'info');
  try {
    const data = await api(`/api/v1/tours/${encodeURIComponent(queryTour)}/validate-addresses`, { method: 'POST' });
    applyAddressResults(data);
    const bad = (data.results || []).filter((r) => !r.valid);
    if (!bad.length) {
      const applied = data.applied ? ` · ${data.applied} von Post übernommen` : '';
      setStatusMsg(msg, `✓ Alle ${data.checked} Adressen bestätigt${applied}`, 'ok');
    } else {
      setStatusMsg(msg, `⚠ ${bad.length} von ${data.checked} Adressen mit Problem – siehe rote Badges`, 'err');
      msg.title = bad.slice(0, 8).map((r) => `${r.recipientName}: ${r.message}`).join('\n');
    }
    renderList();
    updateTourActions();
    await load();
  } catch (e) {
    setStatusMsg(msg, `Adressprüfung: ${e.message}`, 'err');
  }
}

async function saveEdit(withLabel = false) {
  const id = document.getElementById('editId').value;
  document.getElementById('editMsg').classList.add('hidden');
  const payload = buildPayload();
  const liveWeightWarn = weightWarningFor(payload.weight_grams, payload.packstuecke);

  const saveRes = await api(`/api/v1/shipments/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const weightWarn = saveRes.weight_warning || liveWeightWarn;

  if (!withLabel) {
    const bookNote = saveRes.addressBookSaved ? ' · Adressbuch aktualisiert' : '';
    if (weightWarn) setEditMsg(`✓ Gespeichert${bookNote}. ⚠ ${weightWarn}`, 'warn');
    else setEditMsg(`✓ Gespeichert${bookNote}`, 'ok');
    if (saveRes.addressBookSaved) loadAddressBook();
    await load();
    return;
  }

  // Speichern & Label: Adresse prüfen – bei ungültig speichern OK, Label nicht
  try {
    const addr = await api(`/api/v1/shipments/${id}/validate-address`, { method: 'POST' });
    if (!addr.valid) {
      const acceptBtn = document.getElementById('acceptAddressBtn');
      acceptBtn.classList.remove('hidden');
      if (addr.suggested) {
        lastAddressSuggestion = addr.suggested;
        document.getElementById('applySuggestionBtn').classList.remove('hidden');
      }
      let msg = `✓ Adresse gespeichert. Label nicht erzeugt: ${addr.message}`;
      if (weightWarn) msg += ` · ⚠ ${weightWarn}`;
      setEditMsg(msg, 'err');
      await load();
      return;
    }
  } catch (e) {
    setEditMsg(`✓ Gespeichert. Adressprüfung fehlgeschlagen – Label nicht erzeugt: ${e.message}`, 'err');
    await load();
    return;
  }

  try {
    const labelRes = await generateLabel(id, false);
    let msg = '✓ Gespeichert und Label erzeugt';
    const warns = [...(labelRes.warnings || [])];
    if (weightWarn && !warns.includes(weightWarn)) warns.unshift(weightWarn);
    if (warns.length) msg += ` · ⚠ ${warns.join(' · ')}`;
    setEditMsg(msg, warns.length ? 'warn' : 'ok');
  } catch (e) {
    let msg = `✓ Adresse gespeichert. Label nicht erzeugt: ${e.message}`;
    if (weightWarn) msg += ` · ⚠ ${weightWarn}`;
    setEditMsg(msg, 'err');
  }
  await load();
}

async function generateLabel(id, reload = true) {
  const data = await api(`/api/v1/shipments/${id}/generate-label`, { method: 'POST' });
  if (!data.ok) {
    throw new Error(data.error || 'Label fehlgeschlagen');
  }
  if (reload) await load();
  return data;
}

function buildQuery() {
  const params = new URLSearchParams({ open_only: 'false' });
  if (querySearch) {
    params.set('q', querySearch);
    return params.toString();
  }
  if (queryTour) params.set('tour_number', queryTour);
  // Unterwegs / Zugestellt über alle Tage – sonst verschwinden heutige Übergaben mit ältem Tour-Datum
  if (queryDate && filter !== 'tracking' && filter !== 'delivered') {
    params.set('date', queryDate);
  }
  return params.toString();
}

function updateTourActions() {
  const box = document.getElementById('tourActions');
  const zipLink = document.getElementById('tourZipLink');
  const pdfBtn = document.getElementById('tourPdfBtn');
  const msg = document.getElementById('bulkMsg');
  const btn = document.getElementById('bulkLabelsBtn');
  if (!queryTour) {
    box.classList.add('hidden');
    msg.classList.add('hidden');
    setProgress(0, 0);
    return;
  }
  box.classList.remove('hidden');
  const tourUrl = `/api/v1/tours/${encodeURIComponent(queryTour)}`;
  zipLink.href = `${tourUrl}/labels.zip`;
  const pending = shipments.filter(needsLabel);
  const withLabel = shipments.filter((s) => s.label_path || s.identcode);
  const pdfCount = shipments.filter(shipmentHasPdf).length;
  const hasPdf = pdfCount > 0;
  const addrBad = shipments.filter((s) => s.address_valid === false).length;
  const parts = [
    `Tour ${queryTour}: ${shipments.length} Sendung(en)`,
    `${pending.length} ohne Label`,
    `${withLabel.length} mit Label`,
  ];
  if (addrBad) parts.push(`${addrBad} Adresse(n) ungültig`);
  if (msg.classList.contains('hidden') || !msg.textContent || msg.textContent.startsWith('Tour ')) {
    setStatusMsg(msg, parts.join(' · '), 'info');
  }
  btn.textContent = pending.length
    ? `Alle ${pending.length} Labels erzeugen`
    : 'Alle Labels vorhanden';
  btn.disabled = pending.length === 0 || bulkRunning;
  pdfBtn.classList.toggle('hidden', withLabel.length === 0);
  pdfBtn.disabled = !hasPdf;
  pdfBtn.textContent = hasPdf
    ? `Alle ${pdfCount} Labels als PDF`
    : 'PDF (Labels zuerst erzeugen)';
  pdfBtn.title = hasPdf
    ? 'Öffnet ein kombiniertes PDF aller Tour-Labels'
    : 'Zuerst Labels erzeugen, dann PDF drucken';
}

async function bulkGenerateTourLabels() {
  if (!queryTour || bulkRunning) return;
  const pending = shipments.filter(needsLabel);
  if (!pending.length) return;

  bulkRunning = true;
  const btn = document.getElementById('bulkLabelsBtn');
  const msg = document.getElementById('bulkMsg');
  btn.disabled = true;

  let ok = 0;
  let fail = 0;
  const errors = [];

  for (let i = 0; i < pending.length; i += 1) {
    const s = pending[i];
    setProgress(i, pending.length, `Label ${i + 1}/${pending.length}: ${s.recipient_name || 'Sendung'}`);
    try {
      const res = await api(`/api/v1/shipments/${s.id}/generate-label`, { method: 'POST' });
      if (res.ok) ok += 1;
      else {
        fail += 1;
        errors.push(`${s.recipient_name}: ${res.error}`);
      }
    } catch (e) {
      fail += 1;
      errors.push(`${s.recipient_name}: ${e.message}`);
    }
  }

  setProgress(pending.length, pending.length, `Fertig: ${ok} OK, ${fail} Fehler`);
  setStatusMsg(msg, fail ? `⚠ ${ok} Labels erstellt, ${fail} Fehler` : `✓ ${ok} Labels erstellt`, fail ? 'err' : 'ok');
  if (errors.length) msg.title = errors.slice(0, 5).join('\n');

  bulkRunning = false;
  btn.disabled = false;
  await load();
}

async function loadBillingHistory() {
  const box = document.getElementById('billingHistory');
  if (!box) return;
  try {
    const data = await api('/api/v1/billing/imports');
    const items = data.imports || [];
    if (!items.length) {
      box.textContent = 'Noch keine Rechnung importiert.';
      return;
    }
    box.innerHTML = items.slice(0, 5).map((item) => {
      const when = (item.imported_at || '').slice(0, 16).replace('T', ' ');
      const inv = item.invoice_number ? ` · Rechnung ${item.invoice_number}` : '';
      return `<div>${when} · ${item.filename}: ${item.matched_count}/${item.row_count} zugeordnet${inv}</div>`;
    }).join('');
  } catch {
    box.textContent = '';
  }
}

async function importBillingFile() {
  const input = document.getElementById('billingFile');
  const msg = document.getElementById('billingMsg');
  const btn = document.getElementById('billingImportBtn');
  const report = document.getElementById('billingSurchargeReport');
  const file = input?.files?.[0];
  if (!file) {
    setStatusMsg(msg, 'Bitte zuerst Excel/CSV oder Verarbeitungsnachweis-PDF wählen.', 'err');
    return;
  }
  btn.disabled = true;
  if (report) {
    report.classList.add('hidden');
    report.innerHTML = '';
  }
  setStatusMsg(msg, 'Auswertung läuft …', 'info');
  try {
    const body = new FormData();
    body.append('file', file);
    const res = await fetch('/api/v1/billing/import', { method: 'POST', credentials: 'same-origin', body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    const warn = (data.warnings || []).join(' ');
    const extra = data.surcharge_hints ? ` · ${data.surcharge_hints} Mehrkosten-Position(en)` : '';
    const surchargeTotal = data.surcharge_total_chf != null ? ` · Weiterverrechnung CHF ${Number(data.surcharge_total_chf).toFixed(2)}` : '';
    setStatusMsg(
      msg,
      `${data.matched_count}/${data.row_count} Zeilen zugeordnet · Total CHF ${data.total_chf?.toFixed?.(2) ?? data.total_chf}${extra}${surchargeTotal}${warn ? ` · ${warn}` : ''}`,
      data.unmatched_count ? 'info' : 'ok',
    );
    renderBillingSurchargeReport(data.weiterverrechnung || [], data.surcharge_total_chf);
    input.value = '';
    await Promise.all([loadBillingHistory(), load()]);
  } catch (e) {
    setStatusMsg(msg, e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function renderBillingSurchargeReport(rows, total) {
  const box = document.getElementById('billingSurchargeReport');
  if (!box) return;
  if (!rows.length) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  const items = rows.map((r) => {
    const reasons = (r.reasons || []).map((x) => `<li>${escapeHtml(x)}</li>`).join('');
    return `<article class="billing-surcharge-item">
      <div class="billing-surcharge-head">
        <strong>Soloplan ${escapeHtml(r.soloplan || '—')}</strong>
        <span>Mehrkosten CHF ${Number(r.surcharge_chf || 0).toFixed(2)}</span>
      </div>
      <div class="meta">${escapeHtml(r.sender || '—')} → ${escapeHtml(r.recipient || '—')}</div>
      <div class="meta">Ident ${escapeHtml(r.identcode || '—')} · Total Post CHF ${Number(r.total_chf || 0).toFixed(2)}</div>
      <ul>${reasons}</ul>
    </article>`;
  }).join('');
  box.innerHTML = `
    <div class="billing-surcharge-title">Weiterverrechnung Mehrkosten${total != null ? ` · Summe CHF ${Number(total).toFixed(2)}` : ''}</div>
    <div class="billing-surcharge-list">${items}</div>
  `;
  box.classList.remove('hidden');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function load() {
  const data = await api(`/api/v1/shipments?${buildQuery()}`);
  shipments = data.shipments || [];
  updateTourActions();
  updateSearchHint();
  renderKpis(shipments);
  renderList();
}

function updateSearchHint() {
  const hint = document.getElementById('tourHint');
  if (!hint) return;
  if (querySearch) {
    hint.textContent = `Suche „${querySearch}“: ${shipments.length} Treffer (Post-Identcode / Soloplan-Sendungsnummer).`;
  } else if (queryTour) {
    hint.textContent = `Tour ${queryTour} geladen. Sammelaktionen unten verfügbar.`;
  } else {
    hint.textContent = 'Standard: Sendungen von heute ohne Label. Optional Tournummer laden oder nach Post-/Soloplan-Sendungsnummer suchen.';
  }
}

document.getElementById('editForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await saveEdit(false);
});
document.getElementById('saveAndLabelBtn').addEventListener('click', async () => saveEdit(true));
document.getElementById('validateAddressBtn').addEventListener('click', validateCurrentAddress);
document.getElementById('editWeight').addEventListener('input', refreshEditWeightWarning);
document.getElementById('editPackstuecke').addEventListener('input', refreshEditWeightWarning);
document.getElementById('acceptAddressBtn').addEventListener('click', acceptCurrentAddress);
document.getElementById('applySuggestionBtn').addEventListener('click', applyAddressSuggestion);
document.getElementById('validateTourBtn').addEventListener('click', validateTourAddresses);
document.getElementById('closeModal').addEventListener('click', closeEdit);
document.getElementById('editModal').addEventListener('click', (e) => { if (e.target.id === 'editModal') closeEdit(); });

document.querySelectorAll('.tab').forEach((btn) => {
  btn.addEventListener('click', async () => {
    document.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    filter = btn.dataset.filter;
    // Tracking/Zugestellt neu laden (ohne Datumsfilter), sonst fehlen übergebene Touren
    await load();
  });
});

document.getElementById('applyFilters').addEventListener('click', async () => {
  queryTour = document.getElementById('filterTour').value.trim();
  queryDate = document.getElementById('filterDate').value;
  querySearch = '';
  const searchInput = document.getElementById('filterSearch');
  if (searchInput) searchInput.value = '';
  await load();
});

async function runShipmentSearch() {
  querySearch = document.getElementById('filterSearch').value.trim();
  if (!querySearch) {
    await load();
    return;
  }
  // Nummernsuche über alle Status/Tage
  queryTour = '';
  document.getElementById('filterTour').value = '';
  activateTab('all');
  await load();
}

document.getElementById('applySearch').addEventListener('click', runShipmentSearch);
document.getElementById('filterSearch').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    runShipmentSearch();
  }
});

document.getElementById('clearFilters').addEventListener('click', async () => {
  queryTour = '';
  querySearch = '';
  queryDate = todayISO();
  document.getElementById('filterTour').value = '';
  document.getElementById('filterSearch').value = '';
  document.getElementById('filterDate').value = queryDate;
  activateTab('pending');
  document.getElementById('bulkMsg').classList.add('hidden');
  setProgress(0, 0);
  await load();
});

document.getElementById('bulkLabelsBtn').addEventListener('click', bulkGenerateTourLabels);
document.getElementById('tourPdfBtn').addEventListener('click', () => {
  if (!queryTour) return;
  window.open(`/api/v1/tours/${encodeURIComponent(queryTour)}/labels.pdf`, '_blank');
});

document.getElementById('reloadBtn').addEventListener('click', load);
document.getElementById('logoutBtn').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' });
  location.href = '/login';
});

document.getElementById('billingImportBtn').addEventListener('click', importBillingFile);

document.getElementById('filterDate').value = queryDate;

Promise.all([loadProducts(), loadBillingHistory(), load()]).catch(() => { location.href = '/login'; });

document.getElementById('faqToggle')?.addEventListener('click', () => {
  const body = document.getElementById('faqBody');
  const btn = document.getElementById('faqToggle');
  if (!body || !btn) return;
  const open = !body.classList.contains('hidden');
  if (open) {
    body.classList.add('hidden');
    btn.textContent = 'Anzeigen';
    btn.setAttribute('aria-expanded', 'false');
  } else {
    body.classList.remove('hidden');
    btn.textContent = 'Ausblenden';
    btn.setAttribute('aria-expanded', 'true');
    if (!body.dataset.loaded) {
      loadFaq().then(() => { body.dataset.loaded = '1'; });
    }
  }
});

async function loadAddressBook() {
  const box = document.getElementById('addressBookList');
  if (!box) return;
  try {
    const data = await api('/api/v1/address-book');
    const entries = data.entries || [];
    if (!entries.length) {
      box.textContent = 'Noch keine Einträge.';
      box.classList.add('muted');
      return;
    }
    box.classList.remove('muted');
    box.innerHTML = entries.map((e) => `
      <div class="address-book-item" data-id="${e.id}">
        <div>
          <strong>${e.name1 || '—'}${e.name2 ? ` · ${e.name2}` : ''}</strong>
          <div class="meta">${[e.street, e.zip_code, e.city, e.country].filter(Boolean).join(', ')}</div>
          <div class="meta">${e.soloplan_matchcode ? `Matchcode ${e.soloplan_matchcode}` : 'ohne Matchcode (Name+PLZ)'}${e.soloplan_bp_id ? ` · BP ${e.soloplan_bp_id}` : ''}</div>
        </div>
        <button type="button" class="secondary sm" data-del-addr="${e.id}">Löschen</button>
      </div>
    `).join('');
    box.querySelectorAll('[data-del-addr]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Adressbuch-Eintrag löschen?')) return;
        await api(`/api/v1/address-book/${btn.dataset.delAddr}`, { method: 'DELETE' });
        await loadAddressBook();
      });
    });
  } catch (e) {
    box.textContent = `Adressbuch: ${e.message}`;
  }
}

document.getElementById('addressBookToggle')?.addEventListener('click', async () => {
  const body = document.getElementById('addressBookBody');
  const btn = document.getElementById('addressBookToggle');
  const open = body.classList.toggle('hidden') === false;
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  btn.textContent = open ? 'Ausblenden' : 'Anzeigen';
  if (open) await loadAddressBook();
});

