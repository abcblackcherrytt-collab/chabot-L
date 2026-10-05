'use strict';

/* Chabot 管理UI — 本番実装。
 * データはすべて /api/v1/admin/* 経由でFirestoreへ接続する。
 * 書込みはCSRFトークン付きで送信し、401時はセッション再確立を促す。 */

function el(tag, attrs, children) {
  var node = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (key === 'class') { node.className = value; }
      else if (key === 'text') { node.textContent = value; }
      else if (key === 'dataset') {
        Object.keys(value).forEach(function (name) { node.setAttribute('data-' + name, value[name]); });
      }
      else if (key.indexOf('on') === 0) { node.addEventListener(key.slice(2), value); }
      else { node.setAttribute(key, value); }
    });
  }
  (children || []).forEach(function (child) {
    if (child === null || child === undefined) { return; }
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  });
  return node;
}

function clearNode(node) {
  while (node.firstChild) { node.removeChild(node.firstChild); }
}

function badge(text, kind) {
  return el('span', { class: 'badge badge-' + kind, text: text }, []);
}

function planBadge(plan) { return badge(plan, plan); }

function kv(pairs) {
  var dl = el('dl', { class: 'kv' }, []);
  pairs.forEach(function (pair) {
    dl.appendChild(el('div', {}, [
      el('dt', { text: pair[0] }, []),
      el('dd', { text: pair[1] }, [])
    ]));
  });
  return dl;
}

function shortId(value) {
  if (!value) { return '—'; }
  return value.length > 12 ? value.slice(0, 8) + '…' : value;
}

function fmtDate(value) {
  if (!value) { return '—'; }
  var date = new Date(value);
  if (isNaN(date.getTime())) { return value; }
  return date.toLocaleString('ja-JP', { dateStyle: 'medium', timeStyle: 'short' });
}

var sectionTitles = {
  overview: '集計',
  users: 'ユーザー',
  corpora: 'コーパス',
  coupons: 'クーポン',
  invites: '無料登録URL',
  conversations: '会話保管',
  feedback: '要望',
  audit: '監査ログ'
};

var toastRegion = null;

function toast(message, kind) {
  if (!toastRegion) {
    toastRegion = el('div', { class: 'toast-region', 'aria-live': 'polite' }, []);
    document.body.appendChild(toastRegion);
  }
  var item = el('p', { class: 'toast toast-' + (kind || 'info'), text: message }, []);
  toastRegion.appendChild(item);
  window.setTimeout(function () { item.remove(); }, 4200);
}

function confirmDialog(options) {
  var previous = document.querySelector('dialog.confirm-dialog');
  if (previous) { previous.remove(); }
  var dialog = el('dialog', { class: 'confirm-dialog' }, []);
  dialog.appendChild(el('h3', { text: options.title }, []));
  (options.lines || []).forEach(function (line) {
    dialog.appendChild(el('p', { text: line }, []));
  });
  var cancel = el('button', { class: 'btn', type: 'button', text: options.cancelLabel || 'キャンセル' }, []);
  var ok = el('button', { class: 'btn btn-primary', type: 'button', text: options.okLabel || '実行' }, []);
  dialog.appendChild(el('div', { class: 'btn-row' }, [cancel, ok]));
  document.body.appendChild(dialog);
  dialog.addEventListener('close', function () { dialog.remove(); });
  return new Promise(function (resolve) {
    cancel.addEventListener('click', function () { dialog.close(); resolve(false); });
    ok.addEventListener('click', function () { dialog.close(); resolve(true); });
    dialog.showModal();
  });
}

function copyText(text, successMessage) {
  var done = function () { toast(successMessage, 'success'); };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, function () { toast('コピーできませんでした。手動で選択してください。'); });
  } else {
    done();
  }
}

/* ---------- API ---------- */

var session = { email: null, csrfToken: null, authMode: 'iap' };

function apiRequest(method, path, body) {
  var headers = { 'Accept': 'application/json' };
  if (body !== undefined) { headers['Content-Type'] = 'application/json'; }
  if (session.csrfToken) { headers['X-CSRF-Token'] = session.csrfToken; }
  return window.fetch(path, {
    method: method,
    headers: headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin'
  }).then(function (response) {
    if (response.status === 204) { return { ok: true, status: 204, data: null }; }
    return response.json().catch(function () { return null; }).then(function (data) {
      return { ok: response.ok, status: response.status, data: data };
    });
  });
}

function apiError(result) {
  var detail = result && result.data && result.data.detail;
  if (typeof detail === 'string') { return detail; }
  if (detail && detail.reason) { return detail.reason; }
  return 'エラーが発生しました（HTTP ' + (result ? result.status : '?') + '）。';
}

function loadingCard() {
  return el('div', { class: 'card' }, [el('p', { class: 'sub', text: '読み込み中…' }, [])]);
}

function errorCard(message, retry) {
  var card = el('div', { class: 'card' }, [
    el('p', { class: 'error-note', role: 'alert', text: message }, [])
  ]);
  if (retry) {
    card.appendChild(el('div', { class: 'btn-row' }, [
      el('button', { class: 'btn', type: 'button', text: '再読み込み', onclick: retry }, [])
    ]));
  }
  return card;
}

function loadInto(container, fetchFn, renderFn) {
  var target = container;
  target.appendChild(loadingCard());
  fetchFn().then(function (result) {
    clearNode(target);
    if (!result.ok) {
      target.appendChild(errorCard(apiError(result), function () {
        clearNode(target);
        loadInto(target, fetchFn, renderFn);
      }));
      return;
    }
    renderFn(target, result.data);
  }).catch(function () {
    clearNode(target);
    target.appendChild(errorCard('通信エラーが発生しました。', function () {
      clearNode(target);
      loadInto(target, fetchFn, renderFn);
    }));
  });
}

/* ---------- セッション ---------- */

function renderDevLogin(host) {
  var error = el('p', { class: 'error-note', role: 'alert' }, []);
  var email = el('input', { type: 'email', autocomplete: 'username', placeholder: 'admin@example.com' }, []);
  var form = el('form', {}, [
    el('h3', { text: '開発者ログイン' }, []),
    el('p', { class: 'sub', text: 'devモードで動作しています。許可リスト内のメールアドレスでログインできます。' }, []),
    el('div', { class: 'field' }, [el('label', { text: 'メールアドレス' }, []), email]),
    el('div', { class: 'btn-row' }, [
      el('button', { class: 'btn btn-primary', type: 'submit', text: 'ログイン' }, [])
    ]),
    error
  ]);
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearNode(error);
    apiRequest('POST', '/api/v1/admin/dev-login', { email: email.value.trim() }).then(function (result) {
      if (!result.ok) { error.textContent = apiError(result); return; }
      session.email = result.data.email;
      session.csrfToken = result.data.csrf_token;
      startApp();
    });
  });
  host.appendChild(el('div', { class: 'card' }, [form]));
}

function bootstrapSession() {
  var host = document.getElementById('section-host');
  clearNode(host);
  host.appendChild(el('p', { class: 'sub', text: 'セッションを確認しています…' }, []));
  apiRequest('GET', '/api/v1/admin/session').then(function (result) {
    if (result.ok) {
      session.email = result.data.email;
      session.csrfToken = result.data.csrf_token;
      startApp();
      return;
    }
    var detail = result.data && result.data.detail;
    var mode = detail && detail.mode;
    session.authMode = mode || 'iap';
    clearNode(host);
    if (session.authMode === 'dev') {
      renderDevLogin(host);
    } else {
      host.appendChild(errorCard('管理者として認証されていません。Cloud IAPまたは管理プロキシ経由でアクセスしてください。'));
    }
  }).catch(function () {
    clearNode(host);
    host.appendChild(errorCard('管理APIへ接続できませんでした。'));
  });
}

/* ---------- 集計 ---------- */

var statsDays = { daily: 1, weekly: 7, monthly: 30 };
var statsPeriod = 'daily';

function renderOverview(host) {
  var periodNames = { daily: '日次', weekly: '週次', monthly: '月次' };
  var segmented = el('div', { class: 'segmented', role: 'group', 'aria-label': '集計期間' }, []);
  Object.keys(periodNames).forEach(function (key) {
    segmented.appendChild(el('button', {
      type: 'button',
      text: periodNames[key],
      'aria-pressed': String(statsPeriod === key),
      onclick: function () { statsPeriod = key; refreshSection(); }
    }, []));
  });
  host.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '期間別の指標' }, []),
    el('p', { class: 'sub', text: 'admin_daily_stats の範囲集計です。' }, []),
    segmented
  ]));
  var holder = el('div', {}, []);
  host.appendChild(holder);
  loadInto(holder, function () {
    return apiRequest('GET', '/api/v1/admin/stats?days=' + statsDays[statsPeriod]);
  }, function (target, data) {
    var totals = data.totals || {};
    var metrics = [
      ['アクティブユーザー数（延べ）', totals.active_user_count || 0, '人'],
      ['メッセージ数', totals.message_count || 0, '件'],
      ['上限拒否数', totals.denied_by_limit || 0, '件'],
      ['クーポン引き換え', totals.coupon_redemptions || 0, '件'],
      ['要望受付', totals.feedback_count || 0, '件']
    ];
    target.appendChild(el('div', { class: 'metric-grid wide' }, metrics.map(function (m) {
      return el('div', { class: 'metric' }, [
        el('p', { class: 'label', text: m[0] }, []),
        el('p', { class: 'value' }, [String(m[1]), el('span', { class: 'unit', text: m[2] }, [])])
      ]);
    })));
    var list = el('ul', { class: 'timeline' }, []);
    (data.daily || []).slice().reverse().forEach(function (day) {
      list.appendChild(el('li', {}, [
        el('div', { class: 'head' }, [
          el('time', { text: day.date }, []),
          el('span', { class: 'action', text: 'メッセージ ' + (day.message_count || 0) + '件・アクティブ ' + (day.active_user_count || 0) + '人' }, [])
        ])
      ]));
    });
    if (!list.childNodes.length) {
      list.appendChild(el('li', {}, [el('p', { class: 'meta', text: 'まだ統計データがありません。' }, [])]));
    }
    target.appendChild(el('div', { class: 'card' }, [
      el('h3', { text: '日別の内訳' }, []),
      list
    ]));
  });
}

/* ---------- ユーザー ---------- */

var usersFilter = { q: '', plan: 'all', status: 'all' };
var selectedUserId = null;

function effectivePlan(user) {
  var sub = user.subscription_plan || 'free';
  if (sub === 'basic' || sub === 'pro') { return sub; }
  var override = user.plan_override;
  if (override && (override.plan === 'basic' || override.plan === 'pro' || override.plan === 'service')) {
    var valid = true;
    if (override.expires_at) {
      valid = new Date(override.expires_at) > new Date();
    }
    if (valid) { return override.plan; }
  }
  return 'free';
}

function renderUserDetail(host) {
  clearNode(host);
  if (!selectedUserId) { return; }
  var panel = el('section', { class: 'panel', 'aria-label': 'ユーザー詳細' }, []);
  host.appendChild(panel);
  panel.appendChild(loadingCard());
  apiRequest('GET', '/api/v1/admin/users/' + encodeURIComponent(selectedUserId)).then(function (result) {
    clearNode(panel);
    if (!result.ok) {
      panel.appendChild(errorCard(apiError(result)));
      return;
    }
    var user = result.data;
    var stripeActive = (user.subscription_plan === 'basic' || user.subscription_plan === 'pro') &&
      user.subscription_status === 'active';
    var closeButton = el('button', { class: 'btn btn-small', type: 'button', text: '閉じる' }, []);
    closeButton.addEventListener('click', function () {
      selectedUserId = null;
      renderUserDetail(host);
    });
    panel.appendChild(el('div', { class: 'panel-heading' }, [
      el('h3', { text: user.display_name || '(名称未取得)' }, []),
      closeButton
    ]));
    if (stripeActive) { panel.appendChild(el('p', {}, [badge('Stripe契約中', 'warning')])); }
    panel.appendChild(kv([
      ['ユーザーID', user.id],
      ['LINE ID', user.line_user_id || '未取得'],
      ['メール', user.email || '未取得'],
      ['プラン', effectivePlan(user)],
      ['状態', user.is_active ? '有効' : '無効（unfollow等）'],
      ['登録日', fmtDate(user.created_at)],
      ['更新日', fmtDate(user.updated_at)]
    ]));
    if (!user.is_active) { return; }
    var error = el('p', { class: 'error-note', role: 'alert' }, []);
    var planSelect = el('select', {}, [
      el('option', { value: 'free', text: 'free' }, []),
      el('option', { value: 'basic', text: 'basic' }, []),
      el('option', { value: 'pro', text: 'pro' }, []),
      el('option', { value: 'service', text: 'service' }, [])
    ]);
    planSelect.value = effectivePlan(user);
    var form = el('form', {}, [
      el('h4', { text: 'プラン変更' }, []),
      el('div', { class: 'toolbar' }, [
        el('div', { class: 'field' }, [el('label', { text: 'プラン' }, []), planSelect])
      ]),
      el('div', { class: 'btn-row' }, [
        el('button', { class: 'btn btn-primary', type: 'submit', text: 'プランを変更' }, [])
      ]),
      error
    ]);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      clearNode(error);
      if (stripeActive && planSelect.value !== 'free') {
        toast('Stripe契約中のため、Bot側はStripeプランを優先します。', 'info');
      }
      apiRequest('POST', '/api/v1/admin/users/' + encodeURIComponent(user.id) + '/plan', {
        plan: planSelect.value
      }).then(function (result2) {
        if (!result2.ok && result2.status !== 204) { error.textContent = apiError(result2); return; }
        toast('プランを変更しました。', 'success');
        refreshSection();
      });
    });
    panel.appendChild(form);
    var deactivate = el('button', { class: 'btn btn-danger', type: 'button', text: 'ユーザーを無効化' }, []);
    deactivate.addEventListener('click', function () {
      confirmDialog({
        title: 'ユーザーを無効化します',
        lines: ['無効化するとBot利用を停止できます（unfollowと同じ扱い）。'],
        okLabel: '無効化する'
      }).then(function (ok) {
        if (!ok) { return; }
        var why = window.prompt('無効化の理由（必須）') || '';
        if (!why.trim()) { toast('理由が入力されていないため中止しました。'); return; }
        apiRequest('POST', '/api/v1/admin/users/' + encodeURIComponent(user.id) + '/deactivate', {
          reason: why.trim()
        }).then(function (result2) {
          if (!result2.ok && result2.status !== 204) { toast(apiError(result2)); return; }
          toast('ユーザーを無効化しました。', 'success');
          refreshSection();
        });
      });
    });
    panel.appendChild(el('div', { class: 'btn-row' }, [deactivate]));
  });
}

function renderUsers(host) {
  var layout = el('div', { class: 'user-layout' }, []);
  var left = el('div', {}, []);
  var right = el('div', {}, []);
  layout.appendChild(left);
  layout.appendChild(right);
  host.appendChild(layout);

  var search = el('input', { type: 'search', placeholder: '表示名の前方一致' }, []);
  search.value = usersFilter.q;
  var searchTimer = null;
  search.addEventListener('input', function () {
    usersFilter.q = search.value;
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(refreshSection, 350);
  });
  var planSelect = el('select', {}, [
    el('option', { value: 'all', text: 'すべてのプラン' }, []),
    el('option', { value: 'free', text: 'free' }, []),
    el('option', { value: 'basic', text: 'basic' }, []),
    el('option', { value: 'pro', text: 'pro' }, []),
    el('option', { value: 'service', text: 'service' }, [])
  ]);
  planSelect.value = usersFilter.plan;
  planSelect.addEventListener('change', function () { usersFilter.plan = planSelect.value; refreshSection(); });
  var statusSelect = el('select', {}, [
    el('option', { value: 'all', text: 'すべての状態' }, []),
    el('option', { value: 'active', text: '有効' }, []),
    el('option', { value: 'inactive', text: '無効' }, [])
  ]);
  statusSelect.value = usersFilter.status;
  statusSelect.addEventListener('change', function () { usersFilter.status = statusSelect.value; refreshSection(); });

  left.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '登録ユーザー' }, []),
    el('p', { class: 'sub', text: '一覧ではLINE IDをマスク表示します。' }, []),
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field grow' }, [el('label', { text: '検索' }, []), search]),
      el('div', { class: 'field' }, [el('label', { text: 'プラン' }, []), planSelect]),
      el('div', { class: 'field' }, [el('label', { text: '状態' }, []), statusSelect])
    ])
  ]));

  var holder = el('div', {}, []);
  left.appendChild(holder);
  var params = [];
  if (usersFilter.q.trim()) { params.push('q=' + encodeURIComponent(usersFilter.q.trim())); }
  if (usersFilter.plan !== 'all') { params.push('plan=' + usersFilter.plan); }
  if (usersFilter.status !== 'all') { params.push('status_filter=' + usersFilter.status); }
  loadInto(holder, function () {
    return apiRequest('GET', '/api/v1/admin/users' + (params.length ? '?' + params.join('&') : ''));
  }, function (target, data) {
    var users = data.users || [];
    target.appendChild(el('p', { class: 'help', text: users.length + ' 件' }, []));
    if (!users.length) {
      target.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '条件に一致するユーザーがありません。' }, [])]));
      return;
    }
    var rows = users.map(function (user) {
      var detailButton = el('button', { class: 'btn btn-small', type: 'button', text: '詳細' }, []);
      detailButton.addEventListener('click', function () {
        selectedUserId = user.id;
        renderUserDetail(right);
      });
      return el('tr', {}, [
        el('td', { text: user.display_name || '(名称未取得)' }, []),
        el('td', {}, [planBadge(user.effective_plan || effectivePlan(user))]),
        el('td', {}, [user.is_active ? badge('有効', 'active') : badge('無効', 'inactive')]),
        el('td', { text: String(user.today_message_count || 0) }, []),
        el('td', { text: fmtDate(user.created_at) }, []),
        el('td', {}, [detailButton])
      ]);
    });
    target.appendChild(el('div', { class: 'card table-wrap' }, [
      el('table', {}, [
        el('thead', {}, [el('tr', {}, [
          el('th', { scope: 'col', text: '表示名' }, []),
          el('th', { scope: 'col', text: 'プラン' }, []),
          el('th', { scope: 'col', text: '状態' }, []),
          el('th', { scope: 'col', text: '当日利用' }, []),
          el('th', { scope: 'col', text: '登録日' }, []),
          el('th', { scope: 'col', text: '操作' }, [])
        ])]),
        el('tbody', {}, rows)
      ])
    ]));
  });
  renderUserDetail(right);

  var createError = el('p', { class: 'error-note', role: 'alert' }, []);
  var lineId = el('input', { type: 'text', placeholder: 'Uxxxxxxxx…' }, []);
  var createForm = el('form', {}, [
    el('h3', { text: 'LINE ID直指定でfree作成' }, []),
    el('p', { class: 'sub', text: 'テスト・移行用。Messaging APIで実在確認します。' }, []),
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field grow' }, [el('label', { text: 'LINE user ID' }, []), lineId])
    ]),
    el('div', { class: 'btn-row' }, [
      el('button', { class: 'btn', type: 'submit', text: 'freeユーザーを作成' }, [])
    ]),
    createError
  ]);
  createForm.addEventListener('submit', function (event) {
    event.preventDefault();
    clearNode(createError);
    apiRequest('POST', '/api/v1/admin/users/free', { line_user_id: lineId.value.trim() }).then(function (result) {
      if (!result.ok) { createError.textContent = apiError(result); return; }
      toast('freeユーザーを作成しました。', 'success');
      refreshSection();
    });
  });
  host.appendChild(el('div', { class: 'card' }, [createForm]));
}

/* ---------- クーポン ---------- */

function couponSummary(coupon) {
  if (coupon.kind === 'plan_grant') {
    return (coupon.plan || '?') + ' を ' + (coupon.duration_days || '?') + ' 日付与';
  }
  return 'freeの当日回数を ' + (coupon.bonus_free_messages || '?') + ' 回追加';
}

function renderCoupons(host) {
  var reveal = el('div', { class: 'callout', 'aria-live': 'polite' }, []);
  var error = el('p', { class: 'error-note', role: 'alert' }, []);
  var kindSelect = el('select', {}, [
    el('option', { value: 'plan_grant', text: 'プラン付与（plan_grant）' }, []),
    el('option', { value: 'bonus_messages', text: '当日回数追加（bonus_messages）' }, [])
  ]);
  var planSelect = el('select', {}, [
    el('option', { value: 'basic', text: 'basic' }, []),
    el('option', { value: 'pro', text: 'pro' }, [])
  ]);
  var daysInput = el('input', { type: 'number', min: '1', max: '365', value: '14' }, []);
  var bonusInput = el('input', { type: 'number', min: '1', max: '100', value: '5' }, []);
  var maxInput = el('input', { type: 'number', min: '1', max: '10000', value: '20' }, []);
  var expiresInput = el('input', { type: 'date' }, []);
  var noteInput = el('input', { type: 'text', maxlength: '200', placeholder: '用途メモ（任意）' }, []);
  var grantFields = el('div', { class: 'toolbar' }, [
    el('div', { class: 'field' }, [el('label', { text: 'プラン' }, []), planSelect]),
    el('div', { class: 'field' }, [el('label', { text: '付与日数' }, []), daysInput])
  ]);
  var bonusFields = el('div', { class: 'toolbar' }, [
    el('div', { class: 'field' }, [el('label', { text: '追加回数（当日）' }, []), bonusInput])
  ]);
  bonusFields.style.display = 'none';
  kindSelect.addEventListener('change', function () {
    grantFields.style.display = kindSelect.value === 'plan_grant' ? '' : 'none';
    bonusFields.style.display = kindSelect.value === 'bonus_messages' ? '' : 'none';
  });
  var form = el('form', {}, [
    el('h3', { text: 'クーポン発行' }, []),
    el('p', { class: 'sub', text: 'コード平文は発行時のみ表示されます。' }, []),
    el('div', { class: 'toolbar' }, [el('div', { class: 'field' }, [el('label', { text: '種別' }, []), kindSelect])]),
    grantFields,
    bonusFields,
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field' }, [el('label', { text: '最大引き換え数' }, []), maxInput]),
      el('div', { class: 'field' }, [el('label', { text: '有効期限（任意）' }, []), expiresInput]),
      el('div', { class: 'field grow' }, [el('label', { text: 'メモ' }, []), noteInput])
    ]),
    el('div', { class: 'btn-row' }, [
      el('button', { class: 'btn btn-primary', type: 'submit', text: '発行' }, [])
    ]),
    error
  ]);
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearNode(reveal);
    clearNode(error);
    var body = {
      kind: kindSelect.value,
      plan: kindSelect.value === 'plan_grant' ? planSelect.value : null,
      duration_days: kindSelect.value === 'plan_grant' ? parseInt(daysInput.value, 10) : null,
      bonus_free_messages: kindSelect.value === 'bonus_messages' ? parseInt(bonusInput.value, 10) : null,
      max_redemptions: parseInt(maxInput.value, 10),
      note: noteInput.value.trim() || null
    };
    if (expiresInput.value) {
      body.expires_at = new Date(expiresInput.value + 'T23:59:59+09:00').toISOString();
    }
    apiRequest('POST', '/api/v1/admin/coupons', body).then(function (result) {
      if (!result.ok) { error.textContent = apiError(result); return; }
      var code = result.data.code;
      var copy = el('button', { class: 'btn btn-small', type: 'button', text: 'コピー' }, []);
      copy.addEventListener('click', function () { copyText(code, 'クーポンコードをコピーしました。'); });
      reveal.appendChild(el('p', { class: 'code', text: code }, []));
      reveal.appendChild(el('div', { class: 'btn-row' }, [copy]));
      toast('クーポンを発行しました。', 'success');
      refreshCouponList();
    });
  });
  host.appendChild(el('div', { class: 'card' }, [form]));
  host.appendChild(reveal);

  var listHolder = el('div', {}, []);
  host.appendChild(listHolder);
  function refreshCouponList() {
    clearNode(listHolder);
    loadInto(listHolder, function () {
      return apiRequest('GET', '/api/v1/admin/coupons');
    }, function (target, data) {
      var coupons = data.items || [];
      if (!coupons.length) {
        target.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: 'クーポンはまだありません。' }, [])]));
        return;
      }
      var rows = coupons.map(function (coupon) {
        var action = el('span', {}, []);
        if (coupon.status === 'active') {
          var revoke = el('button', { class: 'btn btn-small', type: 'button', text: '失効' }, []);
          revoke.addEventListener('click', function () {
            confirmDialog({
              title: 'クーポンを失効します',
              lines: ['新規引き換えを停止します。付与済みの分は維持されます。'],
              okLabel: '失効する'
            }).then(function (ok) {
              if (!ok) { return; }
              apiRequest('POST', '/api/v1/admin/coupons/' + encodeURIComponent(coupon.id) + '/revoke', {}).then(function (result) {
                if (!result.ok && result.status !== 204) { toast(apiError(result)); return; }
                toast('クーポンを失効しました。', 'success');
                refreshCouponList();
              });
            });
          });
          action.appendChild(revoke);
        }
        return el('tr', {}, [
          el('td', { text: couponSummary(coupon) }, []),
          el('td', { text: (coupon.redeemed_count || 0) + ' / ' + (coupon.max_redemptions || 0) }, []),
          el('td', {}, [coupon.status === 'active' ? badge('有効', 'active') : badge('失効', 'inactive')]),
          el('td', { text: coupon.expires_at ? fmtDate(coupon.expires_at) : '無期限' }, []),
          el('td', { text: coupon.note || '—' }, []),
          el('td', {}, [action])
        ]);
      });
      target.appendChild(el('div', { class: 'card table-wrap' }, [
        el('h3', { text: '発行済みクーポン' }, []),
        el('table', {}, [
          el('thead', {}, [el('tr', {}, [
            el('th', { scope: 'col', text: '内容' }, []),
            el('th', { scope: 'col', text: '引き換え' }, []),
            el('th', { scope: 'col', text: '状態' }, []),
            el('th', { scope: 'col', text: '期限' }, []),
            el('th', { scope: 'col', text: 'メモ' }, []),
            el('th', { scope: 'col', text: '操作' }, [])
          ])]),
          el('tbody', {}, rows)
        ])
      ]));
    });
  }
  refreshCouponList();
}

/* ---------- 無料登録URL ---------- */

function renderInvites(host) {
  var reveal = el('div', { class: 'callout', 'aria-live': 'polite' }, []);
  var error = el('p', { class: 'error-note', role: 'alert' }, []);
  var hours = el('input', { type: 'number', min: '1', max: '720', value: '72' }, []);
  var inviteType = el('select', {}, [
    el('option', { value: 'free', text: '無料アカウント' }, []),
    el('option', { value: 'service', text: 'サービスアカウント（pro相当・無期限）' }, [])
  ]);
  var issueButton = el('button', { class: 'btn btn-primary', type: 'button', text: 'URLを発行' }, []);
  issueButton.addEventListener('click', function () {
    clearNode(reveal);
    clearNode(error);
    apiRequest('POST', '/api/v1/admin/invites', {
      ttl_hours: parseInt(hours.value, 10),
      invite_type: inviteType.value
    }).then(function (result) {
      if (!result.ok) { error.textContent = apiError(result); return; }
      var url = result.data.url;
      var copy = el('button', { class: 'btn btn-small', type: 'button', text: 'コピー' }, []);
      copy.addEventListener('click', function () { copyText(url, '登録URLをコピーしました。'); });
      reveal.appendChild(el('p', { class: 'code', text: url }, []));
      reveal.appendChild(el('div', { class: 'btn-row' }, [copy]));
      toast('登録URLを発行しました。', 'success');
      refreshInviteList();
    });
  });
  host.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '無料登録URL発行' }, []),
    el('p', { class: 'sub', text: '1回限り。LINE Login成功時に消費されます。' }, []),
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field' }, [el('label', { text: 'アカウント種別' }, []), inviteType]),
      el('div', { class: 'field' }, [el('label', { text: '有効期間（時間）' }, []), hours]),
      el('div', { class: 'field' }, [el('label', { text: '' }, []), issueButton])
    ]),
    error
  ]));
  host.appendChild(reveal);

  var listHolder = el('div', {}, []);
  host.appendChild(listHolder);
  function refreshInviteList() {
    clearNode(listHolder);
    loadInto(listHolder, function () {
      return apiRequest('GET', '/api/v1/admin/invites');
    }, function (target, data) {
      var invites = data.items || [];
      if (!invites.length) {
        target.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '発行済みのURLはまだありません。' }, [])]));
        return;
      }
      var rows = invites.map(function (invite) {
        var action = el('span', {}, []);
        if (invite.effective_status === 'unused') {
          var revoke = el('button', { class: 'btn btn-small', type: 'button', text: '失効' }, []);
          revoke.addEventListener('click', function () {
            apiRequest('POST', '/api/v1/admin/invites/' + encodeURIComponent(invite.id) + '/revoke', {}).then(function (result) {
              if (!result.ok && result.status !== 204) { toast(apiError(result)); return; }
              toast('登録URLを失効しました。', 'success');
              refreshInviteList();
            });
          });
          action.appendChild(revoke);
        }
        var statusLabel = {
          unused: badge('未使用', 'active'),
          consumed: badge('使用済み', 'inactive'),
          revoked: badge('失効', 'inactive'),
          expired: badge('期限切れ', 'warning')
        }[invite.effective_status] || badge(invite.effective_status || '?', 'inactive');
        return el('tr', {}, [
          el('td', { text: shortId(invite.id) }, []),
          el('td', { text: invite.invite_type === 'service' ? 'サービス（pro相当）' : '無料' }, []),
          el('td', {}, [statusLabel]),
          el('td', { text: fmtDate(invite.expires_at) }, []),
          el('td', { text: fmtDate(invite.created_at) }, []),
          el('td', { text: invite.consumed_by ? shortId(invite.consumed_by) : '—' }, []),
          el('td', { text: invite.consumed_at ? fmtDate(invite.consumed_at) : '—' }, []),
          el('td', {}, [action])
        ]);
      });
      target.appendChild(el('div', { class: 'card table-wrap' }, [
        el('h3', { text: '発行済みURL' }, []),
        el('table', {}, [
          el('thead', {}, [el('tr', {}, [
            el('th', { scope: 'col', text: 'ID' }, []),
            el('th', { scope: 'col', text: '種別' }, []),
            el('th', { scope: 'col', text: '状態' }, []),
            el('th', { scope: 'col', text: '期限' }, []),
            el('th', { scope: 'col', text: '発行日時' }, []),
            el('th', { scope: 'col', text: '使用者' }, []),
            el('th', { scope: 'col', text: '使用日時' }, []),
            el('th', { scope: 'col', text: '操作' }, [])
          ])]),
          el('tbody', {}, rows)
        ])
      ]));
    });
  }
  refreshInviteList();
}

/* ---------- 会話保管 ---------- */

var selectedConversationId = null;

function renderQuestionForm(panel, question, onSaved) {
  var error = el('p', { class: 'error-note', role: 'alert' }, []);
  var textarea = el('textarea', { rows: '10' }, []);
  textarea.style.width = '100%';
  var questionText = el('p', { class: 'code', text: question.question_text || '' }, []);
  questionText.style.whiteSpace = 'pre-wrap';
  var save = el('button', { class: 'btn btn-primary', type: 'button', text: '代表回答を保存' }, []);
  save.addEventListener('click', function () {
    clearNode(error);
    apiRequest('POST', '/api/v1/admin/conversations/' + encodeURIComponent(question.id) + '/representative-answer', {
      representative_answer: textarea.value
    }).then(function (result) {
      if (!result.ok) { error.textContent = apiError(result); return; }
      toast('代表回答を保存しました。', 'success');
      onSaved();
    });
  });
  panel.appendChild(el('h3', { text: '質問と代表回答' }, []));
  panel.appendChild(questionText);
  panel.appendChild(el('p', { class: 'sub', text: '主目的 ' + (question.question_type || '—') + ' ・ ' + fmtDate(question.created_at) + (question.pii_suspected ? ' ・ PII検知あり' : '') }, []));
  panel.appendChild(el('div', { class: 'field' }, [el('label', { text: '代表回答（あなたの回答を入力）' }, []), textarea]));
  panel.appendChild(el('div', { class: 'btn-row' }, [save]));
  panel.appendChild(error);
}

function renderConversations(host) {
  var questionPanel = el('section', { class: 'panel', 'aria-label': '質問と代表回答' }, []);
  var holder = el('div', {}, []);
  var answersHolder = el('div', {}, []);
  host.appendChild(questionPanel);
  host.appendChild(holder);
  host.appendChild(answersHolder);

  function refreshQuestionPanel() {
    clearNode(questionPanel);
    if (!selectedConversationId) {
      questionPanel.appendChild(el('h3', { text: '質問と代表回答' }, []));
      questionPanel.appendChild(el('p', { class: 'sub', text: '一覧の「質問」を選ぶと、質問本文と代表回答入力欄が表示されます。' }, []));
      return;
    }
    questionPanel.appendChild(loadingCard());
    apiRequest('GET', '/api/v1/admin/conversations/' + encodeURIComponent(selectedConversationId) + '/question').then(function (result) {
      clearNode(questionPanel);
      if (!result.ok) {
        questionPanel.appendChild(errorCard(apiError(result)));
        return;
      }
      renderQuestionForm(questionPanel, result.data, refreshAnswers);
    });
  }

  function refreshAnswers() {
    clearNode(answersHolder);
    loadInto(answersHolder, function () {
      return apiRequest('GET', '/api/v1/admin/representative-answers?limit=50');
    }, function (target, data) {
      var items = data.items || [];
      if (!items.length) {
        target.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '保存済みの代表回答はまだありません。' }, [])]));
        return;
      }
      var rows = items.map(function (item) {
        return el('tr', {}, [
          el('td', { text: fmtDate(item.updated_at) }, []),
          el('td', { text: (item.question_text || '').slice(0, 40) }, []),
          el('td', { text: item.question_type || '—' }, []),
          el('td', { text: (item.representative_answer || '').slice(0, 40) }, [])
        ]);
      });
      target.appendChild(el('div', { class: 'card table-wrap' }, [
        el('h3', { text: '代表回答済み（直近' + items.length + '件）' }, []),
        el('table', {}, [
          el('thead', {}, [el('tr', {}, [
            el('th', { scope: 'col', text: '更新日時' }, []),
            el('th', { scope: 'col', text: '質問（抜粋）' }, []),
            el('th', { scope: 'col', text: '主目的' }, []),
            el('th', { scope: 'col', text: '代表回答（抜粋）' }, [])
          ])]),
          el('tbody', {}, rows)
        ])
      ]));
    });
  }

  loadInto(holder, function () {
    return apiRequest('GET', '/api/v1/admin/conversations?limit=100');
  }, function (target, data) {
    var items = data.items || [];
    var piiCount = items.filter(function (row) { return row.pii_suspected; }).length;
    var rows = items.map(function (row) {
      var action = el('span', {}, []);
      if (!row.denied) {
        var questionButton = el('button', { class: 'btn btn-small', type: 'button', text: '質問' }, []);
        questionButton.addEventListener('click', function () {
          selectedConversationId = row.id;
          refreshQuestionPanel();
        });
        action.appendChild(questionButton);
      }
      return el('tr', {}, [
        el('td', { text: fmtDate(row.created_at) }, []),
        el('td', { text: shortId(row.user_id) }, []),
        el('td', {}, [planBadge(row.plan || 'free')]),
        el('td', { text: row.question_type || '—' }, []),
        el('td', {}, [row.denied ? badge('拒否', 'danger') : document.createTextNode('—')]),
        el('td', {}, [row.pii_suspected ? badge('検知', 'warning') : document.createTextNode('—')]),
        el('td', {}, [action])
      ]);
    });
    if (!rows.length) {
      target.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '保管済みの会話はまだありません。' }, [])]));
      return;
    }
    target.appendChild(el('div', { class: 'card table-wrap' }, [
      el('h3', { text: '保管済み会話（メタデータ）' }, []),
      el('p', { class: 'sub', text: '直近' + items.length + '件・PII検知' + piiCount + '件' }, []),
      el('table', {}, [
        el('thead', {}, [el('tr', {}, [
          el('th', { scope: 'col', text: '日時' }, []),
          el('th', { scope: 'col', text: 'ユーザー' }, []),
          el('th', { scope: 'col', text: 'プラン' }, []),
          el('th', { scope: 'col', text: '主目的' }, []),
          el('th', { scope: 'col', text: '上限拒否' }, []),
          el('th', { scope: 'col', text: 'PII検知' }, []),
          el('th', { scope: 'col', text: '操作' }, [])
        ])]),
        el('tbody', {}, rows)
      ])
    ]));
  });
  refreshQuestionPanel();
  refreshAnswers();
}

/* ---------- コーパス ---------- */

function renderCorpora(host) {
  var holder = el('div', {}, []);
  host.appendChild(holder);
  loadInto(holder, function () {
    return apiRequest('GET', '/api/v1/admin/corpora').then(function (result) {
      if (!result.ok) { return result; }
      return apiRequest('GET', '/api/v1/admin/plan-settings').then(function (settings) {
        if (!settings.ok) { return settings; }
        return { ok: true, status: 200, data: { corpora: result.data, settings: settings.data } };
      });
    });
  }, function (target, data) {
    var items = (data.corpora || {}).items || [];
    var settingsByPlan = {};
    ((data.settings || {}).items || []).forEach(function (setting) {
      settingsByPlan[setting.plan] = setting;
    });
    items.forEach(function (entry) {
      var corpus = entry.corpus || {};
      var card = el('div', { class: 'card' }, [
        el('div', { class: 'corpus-head' }, [
          planBadge(entry.plan)
        ]),
        kv([
          ['モデル', entry.model_name || '既定'],
          ['設定更新日時', fmtDate(entry.updated_at)]
        ])
      ]);
      var setting = settingsByPlan[entry.plan];
      if (setting) {
        var value = setting.draft_daily_message_limit;
        var clamp = function (next) { return Math.min(999, Math.max(1, next)); };
        var input = el('input', { class: 'limit-input', type: 'number', min: '1', max: '999', step: '1', value: String(value), 'aria-label': entry.plan + ' の日次上限' }, []);
        var syncInput = function () { input.value = String(value); };
        input.addEventListener('input', function () {
          var parsed = parseInt(input.value, 10);
          if (!isNaN(parsed)) { value = clamp(parsed); }
        });
        input.addEventListener('blur', syncInput);
        var minus = el('button', { class: 'btn stepper-btn', type: 'button', text: '−', 'aria-label': entry.plan + ' の回数を減らす' }, []);
        var plus = el('button', { class: 'btn stepper-btn', type: 'button', text: '＋', 'aria-label': entry.plan + ' の回数を増やす' }, []);
        minus.addEventListener('click', function () { value = clamp(value - 1); syncInput(); });
        plus.addEventListener('click', function () { value = clamp(value + 1); syncInput(); });
        var publishButton = el('button', { class: 'btn btn-small btn-primary', type: 'button', text: '反映' }, []);
        publishButton.addEventListener('click', function () {
          var parsed = parseInt(input.value, 10);
          if (isNaN(parsed) || String(parsed) !== input.value.trim() || parsed < 1 || parsed > 999) { toast('1〜999の整数を入力してください。'); return; }
          var next = clamp(parsed);
          if (next === setting.daily_message_limit) { toast('変更はありません。'); return; }
          publishButton.disabled = true;
          apiRequest('PUT', '/api/v1/admin/plan-settings/' + entry.plan, {
            daily_message_limit: next,
            base_revision: setting.published_revision
          }).then(function (draftResult) {
            if (!draftResult.ok) { toast(apiError(draftResult)); publishButton.disabled = false; return; }
            return apiRequest('POST', '/api/v1/admin/plan-settings/' + entry.plan + '/publish', {
              revision: setting.published_revision
            }).then(function (pubResult) {
              if (!pubResult.ok) { toast(apiError(pubResult)); publishButton.disabled = false; return; }
              toast(entry.plan + ' の上限を反映しました。', 'success');
              refreshSection();
            });
          }).catch(function () {
            publishButton.disabled = false;
            toast('通信エラーが発生しました。');
          });
        });
        card.appendChild(el('div', { class: 'limit-editor' }, [
          el('span', { class: 'limit-label', text: '日次上限' }, []),
          el('div', { class: 'stepper' }, [minus, input, plus]),
          publishButton
        ]));
        card.appendChild(el('p', { class: 'sub', text: '公開中 ' + setting.daily_message_limit + ' 回/日' + (setting.configured ? '' : '（未設定）') }, []));
      }
      if (entry.firestore_error) {
        card.appendChild(el('p', { class: 'error-note', role: 'alert', text: 'rag_permissionsの読取に失敗しました（' + entry.firestore_error + '）。既定値を表示中。' }, []));
      }
      if (corpus.status === 'ok') {
        var files = corpus.files || [];
        var summary = el('summary', { text: corpus.display_name || '名称未設定' }, []);
        var list = el('ul', { class: 'corpus-files' }, []);
        files.forEach(function (item) {
          list.appendChild(el('li', {}, [
            el('span', { text: item.display_name || '(名称未設定)' }, []),
            item.gcs_uri ? el('code', { text: item.gcs_uri }, []) : null
          ]));
        });
        var details = el('details', { class: 'corpus-details' }, [summary]);
        if (corpus.description) {
          details.appendChild(el('p', { class: 'sub', text: corpus.description }, []));
        }
        details.appendChild(list);
        card.appendChild(details);
      } else if (corpus.status === 'error') {
        card.appendChild(el('p', { class: 'error-note', role: 'alert', text: 'Vertex AIコーパス参照に失敗しました（' + (corpus.error || '不明なエラー') + '）。設定表示は継続しています。' }, []));
      }
      target.appendChild(card);
    });
  });
}

/* ---------- 要望 ---------- */

var feedbackFilter = 'open';

function renderFeedback(host) {
  var holder = el('div', {}, []);
  host.appendChild(holder);
  loadInto(holder, function () {
    var query = feedbackFilter === 'all' ? '' : '?status_filter=' + feedbackFilter;
    return apiRequest('GET', '/api/v1/admin/feedback' + query);
  }, function (target, data) {
    var items = data.items || [];
    var tabs = [
      ['open', '未対応'],
      ['handled', '対応済み'],
      ['all', 'すべて']
    ];
    var segmented = el('div', { class: 'segmented', role: 'group', 'aria-label': '対応状況' }, []);
    tabs.forEach(function (tab) {
      segmented.appendChild(el('button', {
        type: 'button',
        text: tab[1],
        'aria-pressed': String(feedbackFilter === tab[0]),
        onclick: function () { feedbackFilter = tab[0]; refreshSection(); }
      }, []));
    });
    target.appendChild(el('div', { class: 'card' }, [
      el('h3', { text: 'LINE要望' }, []),
      el('p', { class: 'sub', text: '未対応を優先して確認します。' }, []),
      segmented
    ]));
    if (!items.length) {
      target.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '該当する要望がありません。' }, [])]));
      return;
    }
    items.forEach(function (item) {
      var card = el('div', { class: 'card' }, [
        el('div', { class: 'head' }, [
          el('h3', { text: item.display_name || '(名称未取得)' }, []),
          el('time', { text: fmtDate(item.created_at) }, []),
          item.status === 'open' ? badge('未対応', 'warning') : badge('対応済み', 'active')
        ]),
        el('p', { text: item.content }, [])
      ]);
      if (item.status === 'handled') {
        card.appendChild(kv([
          ['管理メモ', item.admin_note || '—'],
          ['対応者', item.handled_by || '—'],
          ['対応日時', fmtDate(item.handled_at)]
        ]));
      } else {
        var note = el('textarea', { 'aria-label': '管理メモ' }, []);
        note.placeholder = '管理メモ（任意）';
        var done = el('button', { class: 'btn btn-primary', type: 'button', text: '対応済みにする' }, []);
        done.addEventListener('click', function () {
          apiRequest('POST', '/api/v1/admin/feedback/' + encodeURIComponent(item.id) + '/status', {
            status: 'handled',
            admin_note: note.value.trim() || null
          }).then(function (result) {
            if (!result.ok && result.status !== 204) { toast(apiError(result)); return; }
            toast('要望を対応済みにしました。', 'success');
            refreshSection();
          });
        });
        card.appendChild(el('div', { class: 'field' }, [el('label', { text: '管理メモ' }, []), note]));
        card.appendChild(el('div', { class: 'btn-row' }, [done]));
      }
      target.appendChild(card);
    });
  });
}

/* ---------- 監査ログ ---------- */

function renderAudit(host) {
  var holder = el('div', {}, []);
  host.appendChild(holder);
  loadInto(holder, function () {
    return apiRequest('GET', '/api/v1/admin/audit-logs?limit=100');
  }, function (target, data) {
    var items = data.items || [];
    var list = el('ul', { class: 'timeline' }, []);
    items.forEach(function (entry) {
      list.appendChild(el('li', {}, [
        el('div', { class: 'head' }, [
          el('time', { text: fmtDate(entry.created_at) }, []),
          el('span', { class: 'action', text: entry.action }, []),
          badge(entry.result || 'success', entry.result === 'success' ? 'active' : 'danger')
        ]),
        el('p', { class: 'meta', text: (entry.actor || '?') + '・' + (entry.target_type || '') + (entry.target_id ? '/' + entry.target_id : '') + (entry.revision ? '・rev ' + entry.revision : '') }, [])
      ]));
    });
    if (!list.childNodes.length) {
      list.appendChild(el('li', {}, [el('p', { class: 'meta', text: '監査ログはまだありません。' }, [])]));
    }
    target.appendChild(el('div', { class: 'card' }, [
      el('h3', { text: '操作履歴' }, []),
      el('p', { class: 'sub', text: '管理操作を新しい順に表示します。' }, []),
      list
    ]));
  });
}

/* ---------- ルーティング ---------- */

var renderers = {
  overview: renderOverview,
  users: renderUsers,
  corpora: renderCorpora,
  coupons: renderCoupons,
  invites: renderInvites,
  conversations: renderConversations,
  feedback: renderFeedback,
  audit: renderAudit
};

function currentSectionFromHash() {
  var name = window.location.hash.replace('#', '');
  return renderers[name] ? name : 'overview';
}

function renderSection(target) {
  var host = document.getElementById('section-host');
  clearNode(host);
  renderers[target](host);
}

function refreshSection() {
  renderSection(currentSectionFromHash());
}

var renderedSection = null;

function setSection(name) {
  var target = renderers[name] ? name : 'overview';
  renderedSection = target;
  document.querySelectorAll('.section-nav button').forEach(function (button) {
    if (button.getAttribute('data-section') === target) {
      button.setAttribute('aria-current', 'page');
    } else {
      button.removeAttribute('aria-current');
    }
  });
  if (window.location.hash !== '#' + target) {
    window.location.hash = target;
  }
  document.title = sectionTitles[target] + ' | Chabot 管理';
  renderSection(target);
}

function startApp() {
  setSection(currentSectionFromHash());
}

function init() {
  document.querySelectorAll('.section-nav button').forEach(function (button) {
    button.addEventListener('click', function () { setSection(button.getAttribute('data-section')); });
  });
  window.addEventListener('hashchange', function () {
    var target = currentSectionFromHash();
    if (target !== renderedSection) { setSection(target); }
  });
  bootstrapSession();
}

document.addEventListener('DOMContentLoaded', init);
