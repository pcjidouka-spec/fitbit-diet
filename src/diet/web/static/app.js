/* diet local web UI — vanilla JS, no dependencies beyond Chart.js global */
'use strict';

// ---------------------------------------------------------------------------
// CSRF / helpers
// ---------------------------------------------------------------------------
const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

/**
 * POST JSON to url. Returns { status: number, body: object }.
 * The browser automatically sends Origin for same-origin requests.
 */
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify(body),
  });
  let parsed;
  try { parsed = await res.json(); } catch { parsed = {}; }
  return { status: res.status, body: parsed };
}

/** Show a temporary toast message. Never uses innerHTML. */
let _toastTimer = null;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}

// ---------------------------------------------------------------------------
// Day DTO rendering
// ---------------------------------------------------------------------------

/**
 * Create a text node safely (never innerHTML).
 * Returns a DocumentFragment containing <dt> + <dd>.
 */
function makeDtDd(label, value) {
  const frag = document.createDocumentFragment();
  const dt = document.createElement('dt');
  dt.textContent = label;
  const dd = document.createElement('dd');
  if (value === null || value === undefined) {
    dd.className = 'null-val';
    dd.textContent = '—';
  } else {
    dd.textContent = String(value);
  }
  frag.appendChild(dt);
  frag.appendChild(dd);
  return frag;
}

async function loadDay() {
  let res;
  try {
    const r = await fetch('/api/day');
    if (r.status === 409) {
      const j = await r.json();
      toast('設定が見つかりません: ' + (j.detail || 'diet init を実行してください'));
      return;
    }
    res = await r.json();
  } catch (e) {
    toast('day 取得エラー: ' + e.message);
    return;
  }

  // --- #summary ---
  const summary = document.getElementById('summary');
  // Clear existing content safely
  while (summary.firstChild) summary.removeChild(summary.firstChild);

  const dl = document.createElement('dl');

  const steps = res.steps !== null && res.steps !== undefined ? res.steps.toLocaleString() + ' 歩' : null;
  const dist = res.distance_km !== null && res.distance_km !== undefined
    ? res.distance_km.toFixed(2) + ' km' : null;
  const exKcal = res.exercise_kcal !== null && res.exercise_kcal !== undefined
    ? res.exercise_kcal.toFixed(0) + ' kcal' : null;

  let weightText = null;
  if (res.weight) {
    const w = res.weight;
    weightText = w.weight_kg.toFixed(1) + ' kg';
    if (w.days_ago > 0) weightText += ' (' + w.days_ago + '日前)';
  }

  const bmrText = res.bmr !== null && res.bmr !== undefined ? res.bmr + ' kcal' : null;

  let intakeText = null;
  if (res.intake) {
    const i = res.intake;
    // display is a formatted string from service; recorded_sum is a number
    intakeText = i.display || (i.decision_kcal + ' kcal (' + i.label + ')');
  }

  dl.appendChild(makeDtDd('歩数', steps));
  dl.appendChild(makeDtDd('距離', dist));
  dl.appendChild(makeDtDd('運動消費', exKcal));
  dl.appendChild(makeDtDd('体重', weightText));
  dl.appendChild(makeDtDd('基礎代謝 (BMR)', bmrText));
  dl.appendChild(makeDtDd('食事 (累積/決定)', intakeText));

  summary.appendChild(dl);

  // --- #balance ---
  const balanceEl = document.getElementById('balance');
  while (balanceEl.firstChild) balanceEl.removeChild(balanceEl.firstChild);
  if (res.balance) {
    balanceEl.textContent = res.balance;
  } else {
    const span = document.createElement('span');
    span.className = 'null-val';
    span.textContent = '体重・活動データが揃うと表示されます';
    balanceEl.appendChild(span);
  }
}

// ---------------------------------------------------------------------------
// History chart
// ---------------------------------------------------------------------------
let _historyChart = null;

async function loadHistory() {
  let rows;
  try {
    const r = await fetch('/api/history?days=30');
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      toast('履歴取得エラー: ' + (j.detail || r.status));
      return;
    }
    rows = await r.json();
  } catch (e) {
    toast('履歴取得エラー: ' + e.message);
    return;
  }

  const labels = rows.map(r => r.date);
  const weightData = rows.map(r => r.weight_kg);
  const stepsData = rows.map(r => r.steps);

  const ctx = document.getElementById('history-chart').getContext('2d');

  // Destroy previous instance to avoid duplicate-canvas errors
  if (_historyChart) {
    _historyChart.destroy();
    _historyChart = null;
  }

  _historyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '体重 (kg)',
          data: weightData,
          borderColor: '#3a7bd5',
          backgroundColor: 'rgba(58,123,213,0.08)',
          yAxisID: 'yWeight',
          tension: 0.3,
          spanGaps: true,
          pointRadius: 3,
        },
        {
          label: '歩数',
          data: stepsData,
          borderColor: '#2ecc71',
          backgroundColor: 'rgba(46,204,113,0.08)',
          yAxisID: 'ySteps',
          tension: 0.2,
          spanGaps: true,
          pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top' },
        tooltip: { callbacks: {
          label: (ctx) => {
            const v = ctx.parsed.y;
            if (v === null || v === undefined) return ctx.dataset.label + ': —';
            if (ctx.dataset.yAxisID === 'yWeight') return ctx.dataset.label + ': ' + v.toFixed(1) + ' kg';
            return ctx.dataset.label + ': ' + v.toLocaleString() + ' 歩';
          },
        }},
      },
      scales: {
        yWeight: {
          type: 'linear', position: 'left',
          title: { display: true, text: '体重 (kg)' },
        },
        ySteps: {
          type: 'linear', position: 'right',
          title: { display: true, text: '歩数' },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Form handlers
// ---------------------------------------------------------------------------

document.getElementById('intake-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('intake-input');
  const raw = input.value.trim();
  if (!raw) return;
  const { status, body } = await postJSON('/api/intake', { raw });
  if (status === 200) {
    input.value = '';
    await loadDay();
  } else {
    toast('食事記録エラー: ' + (body.detail || body.code || String(status)));
  }
});

document.getElementById('weight-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('weight-input');
  const val = parseFloat(input.value);
  if (!isFinite(val) || val <= 0) {
    toast('正の数値を入力してください');
    return;
  }
  const { status, body } = await postJSON('/api/weight', { kg: val });
  if (status === 200) {
    input.value = '';
    await loadDay();
  } else {
    toast('体重記録エラー: ' + (body.detail || body.code || String(status)));
  }
});

// ---------------------------------------------------------------------------
// Sync button
// ---------------------------------------------------------------------------
document.getElementById('sync-btn').addEventListener('click', async () => {
  const btn = document.getElementById('sync-btn');
  btn.disabled = true;
  btn.textContent = '同期中…';
  try {
    const { status, body } = await postJSON('/api/sync', { days: 7 });
    if (status === 401 || body.code === 'reauth_required') {
      toast('再認証が必要です: diet auth を実行してください');
    } else if (status >= 500 || body.ok === false) {
      const warn = Array.isArray(body.warnings) ? body.warnings.join(', ') : (body.warning || body.detail || '');
      toast('同期失敗: ' + warn);
    } else {
      // ok: true
      const warnCount = Array.isArray(body.warnings) ? body.warnings.length : 0;
      let msg = '同期完了 (' + (body.synced || 0) + '日)';
      if (warnCount > 0) msg += ' ※警告 ' + warnCount + '件';
      toast(msg);
    }
    await loadDay();
    await loadHistory();
  } finally {
    btn.disabled = false;
    btn.textContent = '同期（過去7日）';
  }
});

// ---------------------------------------------------------------------------
// Publish button
// ---------------------------------------------------------------------------
document.getElementById('publish-btn').addEventListener('click', async () => {
  const btn = document.getElementById('publish-btn');
  btn.disabled = true;
  btn.textContent = '公開中…';
  try {
    const { status, body } = await postJSON('/api/publish', {});
    if (status === 200 && body.ok) {
      toast('公開完了 (運動・体重を push しました)');
    } else {
      const code = body.code || '';
      const detail = body.detail || code || String(status);
      const codeLabels = {
        publish_no_data: 'データなし',
        publish_blocked: '手動変更あり (CLIで解決してください)',
        publish_git_failed: 'git 操作失敗',
        publish_invalid: 'データ不正',
        publish_unconfigured: '公開先未設定',
        publish_failed: '公開失敗',
      };
      const label = codeLabels[code] ? codeLabels[code] + ': ' : '';
      toast('公開エラー — ' + label + detail);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = '公開（運動・体重のみ公開）';
  }
});

// ---------------------------------------------------------------------------
// Initial load
// ---------------------------------------------------------------------------
loadDay();
loadHistory();
