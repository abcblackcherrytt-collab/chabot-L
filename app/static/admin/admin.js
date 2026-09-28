'use strict';

/* Chabot 管理UI — ローカル開発用モック実装。
 * 本番接続（Firestore / IAP / 管理API）は未実装。全データは架空のモック。 */

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

function pageHead(title, description) {
  return el('div', { class: 'page-head' }, [
    el('h2', { text: title, tabindex: '-1' }, []),
    el('p', { text: description }, [])
  ]);
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

var state = {
  users: [
    { id: 'u-001', name: '佐藤 花子', plan: 'basic', source: 'stripe', status: 'active', today: 12, limit: 100, registered: '2026-08-12', lineId: 'U4f2…9c2a', email: null, profileFetched: '2026-09-01 10:12', stripeActive: true, stripePeriodEnd: '2026-10-12' },
    { id: 'u-002', name: '鈴木 大輝', plan: 'pro', source: 'stripe', status: 'active', today: 87, limit: 500, registered: '2026-08-20', lineId: 'U91a…44fd', email: null, profileFetched: '2026-09-02 08:40', stripeActive: true, stripePeriodEnd: '2026-10-20' },
    { id: 'u-003', name: '高橋 美咲', plan: 'free', source: 'default', status: 'active', today: 3, limit: 3, registered: '2026-09-01', lineId: 'U77c…be10', email: null, profileFetched: '2026-09-01 21:02', stripeActive: false, stripePeriodEnd: null },
    { id: 'u-004', name: '山本 涼介', plan: 'basic', source: 'override', status: 'active', today: 41, limit: 100, registered: '2026-09-05', lineId: 'U20e…77aa', email: null, profileFetched: '2026-09-05 19:22', stripeActive: false, overrideExpires: '2026-09-30' },
    { id: 'u-005', name: '中村 陽菜', plan: 'free', source: 'default', status: 'active', today: 1, limit: 3, registered: '2026-09-18', lineId: 'Ue39…02c5', email: null, profileFetched: '2026-09-18 07:55', stripeActive: false },
    { id: 'u-006', name: '小林 真理', plan: 'free', source: 'default', status: 'inactive', today: 0, limit: 3, registered: '2026-08-25', lineId: 'Ub62…9d31', email: null, profileFetched: '2026-08-25 12:10', stripeActive: false },
    { id: 'u-007', name: '伊藤 健太', plan: 'pro', source: 'stripe', status: 'active', today: 233, limit: 500, registered: '2026-09-10', lineId: 'Uc05…61be', email: null, profileFetched: '2026-09-10 16:48', stripeActive: true, stripePeriodEnd: '2026-10-10' },
    { id: 'u-008', name: '渡辺 朋子', plan: 'free', source: 'override', status: 'active', today: 0, limit: 3, registered: '2026-09-21', lineId: 'U3aa…f8c2', email: null, profileFetched: '2026-09-21 10:31', stripeActive: false, overrideExpires: '2026-10-05' }
  ],
  usersFilter: { q: '', plan: 'all', status: 'all' },
  selectedUserId: null,
  planSettings: {
    free: { label: 'free（既定）', published: 3, draft: 3, revision: 4, updated: '2026-09-15 11:04', history: [
      { rev: 2, limit: 2, date: '2026-09-01 09:00' },
      { rev: 3, limit: 3, date: '2026-09-10 14:20' },
      { rev: 4, limit: 3, date: '2026-09-15 11:04' }
    ] },
    basic: { label: 'basic', published: 100, draft: 100, revision: 5, updated: '2026-09-12 10:11', history: [
      { rev: 4, limit: 100, date: '2026-09-01 09:00' },
      { rev: 5, limit: 100, date: '2026-09-12 10:11' }
    ] },
    pro: { label: 'pro', published: 500, draft: 500, revision: 3, updated: '2026-09-12 10:12', history: [
      { rev: 2, limit: 500, date: '2026-09-01 09:00' },
      { rev: 3, limit: 500, date: '2026-09-12 10:12' }
    ] }
  },
  coupons: [
    { id: 'cpn-901', kind: 'plan_grant', plan: 'basic', days: 14, bonus: null, max: 20, redeemed: 8, status: 'active', expires: '2026-10-15', note: '理学療法士向け' },
    { id: 'cpn-902', kind: 'bonus_messages', plan: 'free', days: null, bonus: 5, max: 50, redeemed: 12, status: 'active', expires: '2026-09-30', note: '無料枠追加体験' },
    { id: 'cpn-903', kind: 'plan_grant', plan: 'pro', days: 7, bonus: null, max: 10, redeemed: 10, status: 'exhausted', expires: '2026-09-20', note: '学会出展用' }
  ],
  invites: [
    { id: 'inv-101', status: 'unused', expires: '2026-09-24 18:00', created: '2026-09-22 11:31', consumedBy: null, consumedAt: null },
    { id: 'inv-102', status: 'consumed', expires: '2026-09-21 18:00', created: '2026-09-20 20:58', consumedBy: 'u-008', consumedAt: '2026-09-20 21:14' },
    { id: 'inv-103', status: 'expired', expires: '2026-09-22 09:00', created: '2026-09-19 09:00', consumedBy: null, consumedAt: null },
    { id: 'inv-104', status: 'revoked', expires: '2026-09-26 09:00', created: '2026-09-18 09:00', consumedBy: null, consumedAt: null }
  ],
  conversations: [
    { date: '2026-09-22 15:51', user: '高橋 美咲', plan: 'free', type: '知識', denied: false, pii: false },
    { date: '2026-09-22 15:40', user: '山本 涼介', plan: 'basic', type: '評価', denied: false, pii: false },
    { date: '2026-09-22 15:22', user: '伊藤 健太', plan: 'pro', type: '所見解釈', denied: false, pii: true },
    { date: '2026-09-22 14:58', user: '高橋 美咲', plan: 'free', type: '上限拒否', denied: true, pii: false },
    { date: '2026-09-22 14:31', user: '鈴木 大輝', plan: 'pro', type: '介入', denied: false, pii: false },
    { date: '2026-09-22 13:47', user: '中村 陽菜', plan: 'free', type: '術後', denied: false, pii: false }
  ],
  feedback: [
    { id: 'fb-201', user: '佐藤 花子', date: '2026-09-22 09:12', status: 'open', content: '回答をもっと短くしてほしいです。', note: null },
    { id: 'fb-202', user: '鈴木 大輝', date: '2026-09-21 20:45', status: 'open', content: '参考文献の出典を必ず表示してほしい。', note: null },
    { id: 'fb-203', user: '中村 陽菜', date: '2026-09-20 11:03', status: 'handled', content: '土日に返信が遅いことがある。', note: '平日案内を追加しました。', handledBy: 'local-admin', handledAt: '2026-09-20 15:20' },
    { id: 'fb-204', user: '伊藤 健太', date: '2026-09-19 08:30', status: 'open', content: 'クーポンコードの入力方法が分かりにくい。', note: null }
  ],
  feedbackFilter: 'open',
  statsPeriod: 'daily',
  stats: {
    daily: { activeUsers: 5, messages: 38, denied: 4, redemptions: 2, feedback: 1 },
    weekly: { activeUsers: 18, messages: 246, denied: 21, redemptions: 9, feedback: 6 },
    monthly: { activeUsers: 42, messages: 1032, denied: 87, redemptions: 31, feedback: 24 }
  },
  audit: [
    { at: '2026-09-22 15:40', actor: 'local-admin', action: '設定反映', target: 'plan_settings/free', revision: 4, result: '成功' },
    { at: '2026-09-22 14:02', actor: 'local-admin', action: 'クーポン発行', target: 'coupons/cpn-902', revision: null, result: '成功' },
    { at: '2026-09-22 11:31', actor: 'local-admin', action: '登録URL発行', target: 'admin_invites/inv-101', revision: null, result: '成功' },
    { at: '2026-09-21 19:05', actor: 'local-admin', action: 'プラン変更', target: 'users/u-004', revision: null, result: '成功' },
    { at: '2026-09-20 15:20', actor: 'local-admin', action: '要望ステータス更新', target: 'feedback/fb-203', revision: null, result: '成功' },
    { at: '2026-09-20 10:12', actor: 'local-admin', action: 'プロフィール再取得', target: 'users/u-001', revision: null, result: '成功' }
  ]
};

var sectionTitles = {
  overview: '集計',
  users: 'ユーザー',
  settings: '回数上限設定',
  coupons: 'クーポン',
  invites: '無料登録URL',
  conversations: '会話保管',
  feedback: '要望',
  audit: '監査ログ'
};

var sectionMeta = {
  overview: '目的別の数値だけを確認できます。統合ダッシュボードは作りません。',
  users: '表示名・プラン・状態で絞り込んで確認できます。LINE IDは詳細画面でのみマスク表示します。',
  settings: '下書き保存 → 差分確認 → 反映の順で進みます。Botへの適用は最大60秒です。',
  coupons: '発行・引き換え状況・失効を管理します。コード平文は発行時のみ1回表示します。',
  invites: '1回限りの無料登録URLを発行します。トークンはURLフラグメントで受け渡します。',
  conversations: '質問と回答のペアを保管します。初期版では本文を表示しません。',
  feedback: 'LINEで受け付けた要望を確認し、対応状況を管理します。',
  audit: '管理操作の時系列記録を確認できます。本文・トークン・個人情報は記録しません。'
};

function nowStamp() {
  var d = new Date();
  function pad(n) { return String(n).padStart(2, '0'); }
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function dateAfterDays(days) {
  var d = new Date();
  d.setDate(d.getDate() + days);
  function pad(n) { return String(n).padStart(2, '0'); }
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

function logAudit(action, target, revision) {
  state.audit.unshift({ at: nowStamp(), actor: 'local-admin', action: action, target: target, revision: revision || null, result: '成功' });
}

var toastRegion = null;
function toast(message, kind) {
  if (!toastRegion) {
    toastRegion = el('div', { class: 'toast-region', role: 'status', 'aria-live': 'polite' }, []);
    document.body.appendChild(toastRegion);
  }
  var item = el('div', { class: 'toast ' + (kind || ''), text: message }, []);
  toastRegion.appendChild(item);
  window.setTimeout(function () { item.remove(); }, 3400);
}

function confirmDialog(options) {
  return new Promise(function (resolve) {
    var dialog = el('dialog', {}, []);
    var body = el('div', { class: 'dialog-body' }, [
      el('h3', { text: options.title }, []),
      options.lines.map(function (line) { return el('p', { text: line }, []); })
    ]);
    var actions = el('div', { class: 'dialog-actions' }, []);
    var cancelButton = el('button', { class: 'btn', type: 'button', text: options.cancelLabel || 'キャンセル', onclick: function () { dialog.close(false); } }, []);
    var okButton = el('button', { class: 'btn ' + (options.danger ? 'btn-danger' : 'btn-primary'), type: 'button', text: options.okLabel || '実行する', onclick: function () { dialog.close(true); } }, []);
    actions.appendChild(cancelButton);
    actions.appendChild(okButton);
    body.appendChild(actions);
    dialog.appendChild(body);
    dialog.addEventListener('close', function () {
      var result = dialog.returnValue === 'true';
      dialog.remove();
      resolve(result);
    });
    document.body.appendChild(dialog);
    dialog.showModal();
  });
}

function copyText(text, successMessage) {
  var done = function (ok) {
    toast(ok ? successMessage : 'コピーできませんでした。画面から直接選択してください。', ok ? 'success' : 'error');
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    return;
  }
  var area = el('textarea', { 'aria-hidden': 'true' }, []);
  area.value = text;
  document.body.appendChild(area);
  area.select();
  var ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  area.remove();
  done(ok);
}

var CODE_CHARS = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
function randomCode(length) {
  var out = '';
  var sum = 0;
  for (var i = 0; i < length; i += 1) {
    var index = Math.floor(Math.random() * CODE_CHARS.length);
    sum += index;
    out += CODE_CHARS[index];
  }
  return out + CODE_CHARS[sum % CODE_CHARS.length];
}

function randomToken() {
  var chars = '0123456789abcdef';
  var out = '';
  for (var i = 0; i < 40; i += 1) { out += chars[Math.floor(Math.random() * chars.length)]; }
  return out;
}

/* ---------- 集計 ---------- */
function renderOverview(host) {
  var periodNames = { daily: '日次', weekly: '週次', monthly: '月次' };
  var segmented = el('div', { class: 'segmented', role: 'group', 'aria-label': '集計期間' }, []);
  Object.keys(periodNames).forEach(function (key) {
    segmented.appendChild(el('button', {
      type: 'button',
      text: periodNames[key],
      'aria-pressed': String(state.statsPeriod === key),
      onclick: function () { state.statsPeriod = key; refreshSection(); }
    }, []));
  });

  var current = state.stats[state.statsPeriod];
  var metrics = [
    ['アクティブユーザー数', current.activeUsers, '人'],
    ['メッセージ数', current.messages, '件'],
    ['上限拒否数', current.denied, '件'],
    ['クーポン引き換え', current.redemptions, '件'],
    ['要望受付', current.feedback, '件']
  ];
  var grid = el('div', { class: 'metric-grid wide' }, metrics.map(function (m) {
    return el('div', { class: 'metric' }, [
      el('p', { class: 'label', text: m[0] }, []),
      el('p', { class: 'value' }, [String(m[1]), el('span', { class: 'unit', text: m[2] }, [])])
    ]);
  }));

  host.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '期間別の指標' }, []),
    el('p', { class: 'sub', text: periodNames[state.statsPeriod] + '・管理者の操作対象を個別に確認します。' }, []),
    segmented,
    el('div', { class: 'spacer-14' }, [])
  ]));
  host.appendChild(grid);
  host.appendChild(el('p', { class: 'help', text: 'データソース: admin_daily_stats（モック）。期間切替は既存ドキュメントの範囲集計です。' }, []));
}

/* ---------- ユーザー ---------- */
function filteredUsers() {
  var f = state.usersFilter;
  var q = f.q.trim();
  return state.users.filter(function (user) {
    if (q && user.name.indexOf(q) !== 0) { return false; }
    if (f.plan !== 'all' && user.plan !== f.plan) { return false; }
    if (f.status !== 'all' && user.status !== f.status) { return false; }
    return true;
  });
}

function sourceLabel(user) {
  if (user.source === 'stripe') { return 'Stripe契約'; }
  if (user.source === 'override') { return 'クーポン・管理者指定（期限 ' + (user.overrideExpires || '未設定') + '）'; }
  return '既定（free）';
}

function renderUserDetail(host) {
  var panel = el('section', { class: 'panel', 'aria-label': 'ユーザー詳細' }, []);
  var user = state.users.filter(function (item) { return item.id === state.selectedUserId; })[0];
  if (!user) {
    panel.appendChild(el('h3', { text: 'ユーザー詳細' }, []));
    panel.appendChild(el('p', { class: 'sub', text: '一覧の「詳細」を選ぶと、ここに情報が表示されます。' }, []));
    host.appendChild(panel);
    return;
  }
  panel.appendChild(el('h3', { text: user.name }, []));
  if (user.stripeActive) {
    panel.appendChild(el('p', {}, [badge('Stripe契約中', 'warning')]));
  }
  panel.appendChild(kv([
    ['ユーザーID', user.id],
    ['LINE ID（マスク）', user.lineId],
    ['メール', user.email || '未取得'],
    ['プラン', user.plan],
    ['判定経路', sourceLabel(user)],
    ['状態', user.status === 'active' ? '有効' : '無効（unfollow）'],
    ['当日利用', user.today + ' / ' + user.limit + ' 回'],
    ['登録日', user.registered],
    ['プロフィール最終取得', user.profileFetched]
  ]));

  var error = el('p', { class: 'error-note', role: 'alert' }, []);
  var planSelect = el('select', { id: 'plan-select-' + user.id }, [
    el('option', { value: 'free', text: 'free' }, []),
    el('option', { value: 'basic', text: 'basic' }, []),
    el('option', { value: 'pro', text: 'pro' }, [])
  ]);
  planSelect.value = user.plan;
  var reason = el('textarea', { id: 'plan-reason-' + user.id, 'aria-label': '変更理由（必須）' }, []);
  reason.placeholder = '変更理由を入力（必須）';

  panel.appendChild(el('form', {}, [
    el('h4', { text: 'プラン変更' }, []),
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field' }, [el('label', { text: 'プラン' }, []), planSelect]),
      el('div', { class: 'field grow' }, [el('label', { text: '理由' }, []), reason])
    ]),
    el('div', { class: 'btn-row' }, [
      el('button', { class: 'btn btn-primary', type: 'submit', text: 'プランを変更' }, [])
    ]),
    error
  ]));

  var form = panel.querySelector('form');
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearNode(error);
    var nextPlan = planSelect.value;
    var reasonText = reason.value.trim();
    if (!reasonText) {
      error.textContent = '変更理由は必須です。';
      return;
    }
    var applyChange = function () {
      user.plan = nextPlan;
      user.source = 'override';
      user.limit = state.planSettings[nextPlan].published;
      user.overrideExpires = dateAfterDays(30);
      logAudit('プラン変更', 'users/' + user.id);
      toast('プランを ' + nextPlan + ' へ変更しました（モック）。', 'success');
      refreshSection();
    };
    if (user.stripeActive) {
      confirmDialog({
        title: 'Stripe契約と競合します',
        lines: [
          'このユーザーには有効なStripe契約があります。プラン解決ではStripe契約が優先されます。',
          '管理者指定を記録しても、表示プランは契約プランになります。続行しますか？'
        ],
        okLabel: '競合を理解して記録'
      }).then(function (ok) { if (ok) { applyChange(); } });
      return;
    }
    applyChange();
  });

  if (user.status === 'active') {
    var deactivate = el('button', { class: 'btn btn-danger', type: 'button', text: '無効化する' }, []);
    deactivate.addEventListener('click', function () {
      confirmDialog({
        title: 'ユーザーを無効化します',
        lines: ['unfollowと同じ扱いで is_active=false にします。削除は行いません。'],
        danger: true,
        okLabel: '無効化する'
      }).then(function (ok) {
        if (!ok) { return; }
        user.status = 'inactive';
        logAudit('ユーザー無効化', 'users/' + user.id);
        toast('ユーザーを無効化しました（モック）。', 'success');
        refreshSection();
      });
    });
    panel.appendChild(el('div', { class: 'btn-row' }, [deactivate]));
  } else {
    panel.appendChild(el('p', { class: 'help', text: '無効化済みユーザー。再開発は本番実装で対応します。' }, []));
  }
  host.appendChild(panel);
}

function renderUsers(host) {
  var layout = el('div', { class: 'user-layout' }, []);
  var left = el('div', {}, []);
  var right = el('div', {}, []);
  layout.appendChild(left);
  layout.appendChild(right);

  var search = el('input', { type: 'search', placeholder: '表示名の前方一致' });
  search.value = state.usersFilter.q;
  search.addEventListener('input', function () {
    state.usersFilter.q = search.value;
    refreshSection();
    var next = document.querySelector("input[type='search']");
    if (next) { next.focus(); next.setSelectionRange(next.value.length, next.value.length); }
  });
  var planSelect = el('select', {}, [
    el('option', { value: 'all', text: 'すべてのプラン' }, []),
    el('option', { value: 'free', text: 'free' }, []),
    el('option', { value: 'basic', text: 'basic' }, []),
    el('option', { value: 'pro', text: 'pro' }, [])
  ]);
  planSelect.value = state.usersFilter.plan;
  planSelect.addEventListener('change', function () { state.usersFilter.plan = planSelect.value; refreshSection(); });
  var statusSelect = el('select', {}, [
    el('option', { value: 'all', text: 'すべての状態' }, []),
    el('option', { value: 'active', text: '有効' }, []),
    el('option', { value: 'inactive', text: '無効' }, [])
  ]);
  statusSelect.value = state.usersFilter.status;
  statusSelect.addEventListener('change', function () { state.usersFilter.status = statusSelect.value; refreshSection(); });

  left.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '登録ユーザー' }, []),
    el('p', { class: 'sub', text: '氏名はすべて架空のモックデータです。' }, []),
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field grow' }, [el('label', { text: '検索' }, []), search]),
      el('div', { class: 'field' }, [el('label', { text: 'プラン' }, []), planSelect]),
      el('div', { class: 'field' }, [el('label', { text: '状態' }, []), statusSelect])
    ])
  ]));

  var users = filteredUsers();
  var countNote = el('p', { class: 'help', text: users.length + ' 件（ページネーションは本番実装で対応）' }, []);
  left.appendChild(countNote);

  if (!users.length) {
    left.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '条件に一致するユーザーがありません。' }, [])]));
  } else {
    var rows = users.map(function (user) {
      var detailButton = el('button', { class: 'btn btn-small', type: 'button', text: '詳細' });
      detailButton.addEventListener('click', function () {
        state.selectedUserId = user.id;
        refreshSection();
      });
      return el('tr', {}, [
        el('td', { text: user.name }, []),
        el('td', {}, [planBadge(user.plan)]),
        el('td', {}, [user.status === 'active' ? badge('有効', 'active') : badge('無効', 'inactive')]),
        el('td', { text: user.today + ' / ' + user.limit }, []),
        el('td', { text: user.registered }, []),
        el('td', {}, [detailButton])
      ]);
    });
    left.appendChild(el('div', { class: 'card table-wrap' }, [
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
  }

  renderUserDetail(right);
  host.appendChild(layout);
}

/* ---------- 回数上限設定 ---------- */
function parseLimit(value) {
  if (!/^[0-9]+$/.test(value)) { return null; }
  var parsed = parseInt(value, 10);
  if (parsed < 1 || parsed > 999) { return null; }
  return parsed;
}

function renderSettings(host) {
  var grid = el('div', { class: 'settings-grid' }, []);
  Object.keys(state.planSettings).forEach(function (plan) {
    var setting = state.planSettings[plan];
    var error = el('p', { class: 'error-note', role: 'alert' }, []);
    var draftInput = el('input', { type: 'number', min: '1', max: '999', step: '1', value: String(setting.draft), 'aria-label': plan + ' の下書き上限' });

    var saveDraft = function () {
      clearNode(error);
      var parsed = parseLimit(draftInput.value);
      if (parsed === null) { error.textContent = '1〜999の整数を入力してください。'; return; }
      setting.draft = parsed;
      toast(plan + ' の下書きを保存しました。Bot挙動は変わりません。', 'success');
    };
    var showDiff = function () {
      clearNode(error);
      var parsed = parseLimit(draftInput.value);
      if (parsed === null) { error.textContent = '1〜999の整数を入力してください。'; return; }
      setting.draft = parsed;
      confirmDialog({
        title: '差分確認',
        lines: ['公開中: ' + setting.published + ' 回/日', '下書き: ' + setting.draft + ' 回/日'],
        okLabel: '差分を確認しました'
      });
    };
    var publish = function () {
      clearNode(error);
      var parsed = parseLimit(draftInput.value);
      if (parsed === null) { error.textContent = '1〜999の整数を入力してください。'; return; }
      if (parsed === setting.published) { toast('下書きが公開値と同じため、反映しません。'); return; }
      setting.draft = parsed;
      confirmDialog({
        title: plan + ' の上限を反映します',
        lines: [setting.published + ' 回/日 → ' + setting.draft + ' 回/日', 'Botへの適用は最大60秒です。'],
        okLabel: '反映する'
      }).then(function (ok) {
        if (!ok) { return; }
        setting.published = setting.draft;
        setting.revision += 1;
        setting.updated = nowStamp();
        setting.history.push({ rev: setting.revision, limit: setting.published, date: setting.updated });
        logAudit('設定反映', 'plan_settings/' + plan, setting.revision);
        toast(plan + ' を反映しました（rev ' + setting.revision + '・Bot適用は最大60秒）。', 'success');
        refreshSection();
      });
    };

    var card = el('div', { class: 'card' }, [
      el('h3', { text: setting.label }, []),
      el('p', { class: 'sub', text: '公開中 ' + setting.published + ' 回/日・revision ' + setting.revision + '・' + setting.updated }, []),
      el('div', { class: 'field' }, [el('label', { text: '下書き上限（1日あたり）' }, []), draftInput]),
      el('div', { class: 'btn-row' }, [
        el('button', { class: 'btn', type: 'button', text: '下書き保存', onclick: saveDraft }, []),
        el('button', { class: 'btn', type: 'button', text: '差分確認', onclick: showDiff }, []),
        el('button', { class: 'btn btn-primary', type: 'button', text: '反映', onclick: publish }, [])
      ]),
      error
    ]);

    var historyList = el('ul', { class: 'timeline', 'aria-label': plan + ' の公開履歴' }, []);
    setting.history.slice().reverse().forEach(function (entry) {
      var isCurrent = entry.rev === setting.revision;
      var rollback = el('button', { class: 'btn btn-small', type: 'button', text: 'この値へ戻す', disabled: isCurrent ? 'disabled' : null });
      rollback.addEventListener('click', function () {
        confirmDialog({
          title: '設定をロールバックします',
          lines: ['rev ' + entry.rev + ' の ' + entry.limit + ' 回/日を新しいrevisionとして反映します。'],
          okLabel: 'ロールバック'
        }).then(function (ok) {
          if (!ok) { return; }
          setting.published = entry.limit;
          setting.draft = entry.limit;
          setting.revision += 1;
          setting.updated = nowStamp();
          setting.history.push({ rev: setting.revision, limit: entry.limit, date: setting.updated });
          logAudit('設定ロールバック', 'plan_settings/' + plan, setting.revision);
          toast('ロールバックしました（rev ' + setting.revision + '）。', 'success');
          refreshSection();
        });
      });
      historyList.appendChild(el('li', {}, [
        el('div', { class: 'head' }, [
          el('time', { text: entry.date }, []),
          el('span', { class: 'action', text: 'rev ' + entry.rev + '・' + entry.limit + ' 回/日' }, [])
        ]),
        el('div', { class: 'btn-row' }, [rollback])
      ]));
    });
    var historyCard = el('div', { class: 'card' }, [
      el('h3', { text: setting.label + ' の公開履歴' }, []),
      el('p', { class: 'sub', text: '直前のrevisionへ戻せます。' }, []),
      historyList
    ]);
    grid.appendChild(el('div', {}, [card, historyCard]));
  });
  host.appendChild(grid);
  host.appendChild(el('p', { class: 'help', text: '下書き保存ではBot挙動が変わりません。反映はFirestore Transactionで公開revisionを切り替えます（本番実装）。' }, []));
}

/* ---------- クーポン ---------- */
function couponSummary(coupon) {
  if (coupon.kind === 'plan_grant') {
    return coupon.plan + ' を ' + coupon.days + ' 日付与';
  }
  return 'freeの当日回数を ' + coupon.bonus + ' 回追加';
}

function renderCoupons(host) {
  var reveal = el('div', { class: 'callout', 'aria-live': 'polite' }, []);
  var error = el('p', { class: 'error-note', role: 'alert' }, []);
  var kindSelect = el('select', {}, [
    el('option', { value: 'plan_grant', text: 'プラン付与（plan_grant）' }, []),
    el('option', { value: 'bonus_messages', text: '当日回数追加（bonus_messages）' }, [])
  ]);
  var grantFields = el('div', { class: 'toolbar' }, [
    el('div', { class: 'field' }, [
      el('label', { text: '付与プラン' }, []),
      el('select', {}, [el('option', { value: 'basic', text: 'basic' }, []), el('option', { value: 'pro', text: 'pro' }, [])])
    ]),
    el('div', { class: 'field' }, [el('label', { text: '付与日数' }, []), el('input', { type: 'number', min: '1', max: '365', value: '14' })])
  ]);
  var bonusField = el('div', { class: 'field', hidden: 'hidden' }, [
    el('label', { text: '追加回数' }, []),
    el('input', { type: 'number', min: '1', max: '100', value: '5' })
  ]);
  kindSelect.addEventListener('change', function () {
    var isGrant = kindSelect.value === 'plan_grant';
    grantFields.hidden = isGrant ? null : 'hidden';
    bonusField.hidden = isGrant ? 'hidden' : null;
  });
  var maxInput = el('input', { type: 'number', min: '1', max: '10000', value: '20' });
  var daysInput = el('input', { type: 'number', min: '1', max: '180', value: '14' });
  var noteInput = el('input', { type: 'text', placeholder: '用途メモ（任意）' });

  var form = el('form', { class: 'card' }, [
    el('h3', { text: 'クーポン発行' }, []),
    el('p', { class: 'sub', text: 'コード平文は発行時のみ1回表示します。本番ではSHA-256ハッシュのみ保存します。' }, []),
    el('div', { class: 'field' }, [el('label', { text: '種別' }, []), kindSelect]),
    el('div', { class: 'spacer-10' }, []),
    grantFields,
    bonusField,
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field' }, [el('label', { text: '最大引き換え数' }, []), maxInput]),
      el('div', { class: 'field' }, [el('label', { text: '有効期限（日数後）' }, []), daysInput]),
      el('div', { class: 'field grow' }, [el('label', { text: 'メモ' }, []), noteInput])
    ]),
    el('div', { class: 'btn-row' }, [el('button', { class: 'btn btn-primary', type: 'submit', text: '発行する' }, [])]),
    error
  ]);

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearNode(error);
    clearNode(reveal);
    var max = parseLimit(maxInput.value);
    var days = parseInt(daysInput.value, 10);
    if (max === null || !(days >= 1 && days <= 180)) {
      error.textContent = '最大引き換え数（1〜999）と有効期限（1〜180日）を確認してください。';
      return;
    }
    var coupon = {
      id: 'cpn-' + String(900 + state.coupons.length + 1),
      kind: kindSelect.value,
      plan: 'free',
      days: null,
      bonus: null,
      max: max,
      redeemed: 0,
      status: 'active',
      expires: dateAfterDays(days),
      note: noteInput.value.trim() || null
    };
    if (coupon.kind === 'plan_grant') {
      coupon.plan = grantFields.querySelector('select').value;
      coupon.days = parseInt(grantFields.querySelector('input').value, 10);
      if (!(coupon.days >= 1 && coupon.days <= 365)) { error.textContent = '付与日数は1〜365で入力してください。'; return; }
    } else {
      coupon.bonus = parseInt(bonusField.querySelector('input').value, 10);
      if (!(coupon.bonus >= 1 && coupon.bonus <= 100)) { error.textContent = '追加回数は1〜100で入力してください。'; return; }
    }
    var code = randomCode(9);
    state.coupons.unshift(coupon);
    logAudit('クーポン発行', 'coupons/' + coupon.id);
    reveal.appendChild(el('p', { text: 'クーポンコード（この画面でのみ表示・モック生成）' }, []));
    reveal.appendChild(el('code', { text: code }, []));
    var copy = el('button', { class: 'btn btn-small', type: 'button', text: 'コピー' }, []);
    copy.addEventListener('click', function () { copyText(code, 'クーポンコードをコピーしました。'); });
    reveal.appendChild(copy);
    reveal.appendChild(el('p', { class: 'note', text: '平文は再表示できません。一覧にはハッシュ接頭辞のみ表示します。' }, []));
    toast('クーポン ' + coupon.id + ' を発行しました（モック）。', 'success');
    refreshSection();
  });

  host.appendChild(form);
  host.appendChild(reveal);

  var rows = state.coupons.map(function (coupon) {
    var statusNode = coupon.status === 'active' ? badge('有効', 'active') : (coupon.status === 'revoked' ? badge('失効', 'danger') : badge('上限到達', 'inactive'));
    var action = null;
    if (coupon.status === 'active') {
      action = el('button', { class: 'btn btn-small btn-danger', type: 'button', text: '失効' }, []);
      action.addEventListener('click', function () {
        confirmDialog({
          title: 'クーポンを失効します',
          lines: ['新規引き換えのみ停止します。付与済みの特典は維持されます。'],
          danger: true,
          okLabel: '失効する'
        }).then(function (ok) {
          if (!ok) { return; }
          coupon.status = 'revoked';
          logAudit('クーポン失効', 'coupons/' + coupon.id);
          toast('クーポンを失効しました（モック）。', 'success');
          refreshSection();
        });
      });
    }
    return el('tr', {}, [
      el('td', { text: coupon.id }, []),
      el('td', { text: coupon.kind === 'plan_grant' ? 'プラン付与' : '回数追加' }, []),
      el('td', { text: couponSummary(coupon) }, []),
      el('td', { text: coupon.redeemed + ' / ' + coupon.max }, []),
      el('td', { text: coupon.expires }, []),
      el('td', {}, [statusNode]),
      el('td', {}, [action])
    ]);
  });
  host.appendChild(el('div', { class: 'card table-wrap' }, [
    el('h3', { text: 'クーポン一覧' }, []),
    el('p', { class: 'sub', text: '引き換え状況と残数を確認できます。' }, []),
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { scope: 'col', text: 'ID' }, []),
        el('th', { scope: 'col', text: '種別' }, []),
        el('th', { scope: 'col', text: '内容' }, []),
        el('th', { scope: 'col', text: '引き換え' }, []),
        el('th', { scope: 'col', text: '有効期限' }, []),
        el('th', { scope: 'col', text: '状態' }, []),
        el('th', { scope: 'col', text: '操作' }, [])
      ])]),
      el('tbody', {}, rows)
    ])
  ]));
}

/* ---------- 無料登録URL ---------- */
function renderInvites(host) {
  var reveal = el('div', { class: 'callout warning', 'aria-live': 'polite' }, []);
  var expirySelect = el('select', {}, [
    el('option', { value: '1', text: '24時間後' }, []),
    el('option', { value: '3', text: '72時間後' }, []),
    el('option', { value: '7', text: '7日後' }, [])
  ]);
  var issueButton = el('button', { class: 'btn btn-primary', type: 'button', text: '登録URLを発行' }, []);
  issueButton.addEventListener('click', function () {
    clearNode(reveal);
    var token = randomToken();
    var url = window.location.origin + '/claim#' + token;
    var invite = {
      id: 'inv-' + String(100 + state.invites.length + 1),
      status: 'unused',
      expires: dateAfterDays(parseInt(expirySelect.value, 10)) + ' 23:59',
      created: nowStamp(),
      consumedBy: null,
      consumedAt: null
    };
    state.invites.unshift(invite);
    logAudit('登録URL発行', 'admin_invites/' + invite.id);
    reveal.appendChild(el('p', { text: '発行しました（トークンは再表示できません）' }, []));
    reveal.appendChild(el('code', { text: url }, []));
    var copy = el('button', { class: 'btn btn-small', type: 'button', text: 'コピー' }, []);
    copy.addEventListener('click', function () { copyText(url, '登録URLをコピーしました。'); });
    reveal.appendChild(copy);
    reveal.appendChild(el('p', { class: 'note', text: '本番ではURLフラグメントで受け渡し、claim landingで短期セッションへ移行します。' }, []));
    toast('登録URL ' + invite.id + ' を発行しました（モック）。', 'success');
    refreshSection();
  });

  host.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '登録URL発行' }, []),
    el('p', { class: 'sub', text: '1回限り。LINE Login完了時に消費されます。' }, []),
    el('div', { class: 'toolbar' }, [
      el('div', { class: 'field' }, [el('label', { text: '有効期限' }, []), expirySelect]),
      el('div', { class: 'field' }, [el('label', { text: '発行' }, []), issueButton])
    ])
  ]));
  host.appendChild(reveal);

  var statusBadge = { unused: ['未使用', 'active'], consumed: ['使用済み', 'inactive'], expired: ['期限切れ', 'warning'], revoked: ['失効', 'danger'] };
  var rows = state.invites.map(function (invite) {
    var meta = statusBadge[invite.status];
    var action = null;
    if (invite.status === 'unused') {
      action = el('button', { class: 'btn btn-small btn-danger', type: 'button', text: '失効' }, []);
      action.addEventListener('click', function () {
        confirmDialog({ title: '登録URLを失効します', lines: ['未使用のURLを無効化します。'], danger: true, okLabel: '失効する' }).then(function (ok) {
          if (!ok) { return; }
          invite.status = 'revoked';
          logAudit('登録URL失効', 'admin_invites/' + invite.id);
          toast('登録URLを失効しました（モック）。', 'success');
          refreshSection();
        });
      });
    }
    return el('tr', {}, [
      el('td', { text: invite.id }, []),
      el('td', {}, [badge(meta[0], meta[1])]),
      el('td', { text: invite.expires }, []),
      el('td', { text: invite.created }, []),
      el('td', { text: invite.consumedBy ? invite.consumedBy + '（' + invite.consumedAt + '）' : '—' }, []),
      el('td', {}, [action])
    ]);
  });
  host.appendChild(el('div', { class: 'card table-wrap' }, [
    el('h3', { text: '発行済みURL' }, []),
    el('p', { class: 'sub', text: '状態と消費者を確認できます。' }, []),
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { scope: 'col', text: 'ID' }, []),
        el('th', { scope: 'col', text: '状態' }, []),
        el('th', { scope: 'col', text: '有効期限' }, []),
        el('th', { scope: 'col', text: '作成日時' }, []),
        el('th', { scope: 'col', text: '使用者' }, []),
        el('th', { scope: 'col', text: '操作' }, [])
      ])]),
      el('tbody', {}, rows)
    ])
  ]));
}

/* ---------- 会話保管 ---------- */
function renderConversations(host) {
  host.appendChild(el('p', { class: 'notice', text: '初期版では本文を表示しません。件数とメタデータのみ確認できます。' }, []));
  var piiCount = state.conversations.filter(function (row) { return row.pii; }).length;
  var rows = state.conversations.map(function (row) {
    return el('tr', {}, [
      el('td', { text: row.date }, []),
      el('td', { text: row.user }, []),
      el('td', {}, [planBadge(row.plan)]),
      el('td', { text: row.type }, []),
      el('td', {}, [row.denied ? badge('拒否', 'danger') : document.createTextNode('—')]),
      el('td', {}, [row.pii ? badge('検知', 'warning') : document.createTextNode('—')])
    ]);
  });
  host.appendChild(el('div', { class: 'card table-wrap' }, [
    el('h3', { text: '保管済み会話（メタデータ）' }, []),
    el('p', { class: 'sub', text: '総' + state.conversations.length + '件・PII検知' + piiCount + '件（架空データ）' }, []),
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { scope: 'col', text: '日時' }, []),
        el('th', { scope: 'col', text: 'ユーザー' }, []),
        el('th', { scope: 'col', text: 'プラン' }, []),
        el('th', { scope: 'col', text: '主目的' }, []),
        el('th', { scope: 'col', text: '上限拒否' }, []),
        el('th', { scope: 'col', text: 'PII検知' }, [])
      ])]),
      el('tbody', {}, rows)
    ])
  ]));
  host.appendChild(el('p', { class: 'help', text: '保持期間は未決定（設計書10節）。本文閲覧は監査記録付きの個別権限として将来追加します。' }, []));
}

/* ---------- 要望 ---------- */
function renderFeedback(host) {
  var openCount = state.feedback.filter(function (item) { return item.status === 'open'; }).length;
  var handledCount = state.feedback.length - openCount;
  var tabs = [
    ['open', '未対応 ' + openCount],
    ['handled', '対応済み ' + handledCount],
    ['all', 'すべて ' + state.feedback.length]
  ];
  var segmented = el('div', { class: 'segmented', role: 'group', 'aria-label': '対応状況' }, []);
  tabs.forEach(function (tab) {
    segmented.appendChild(el('button', {
      type: 'button',
      text: tab[1],
      'aria-pressed': String(state.feedbackFilter === tab[0]),
      onclick: function () { state.feedbackFilter = tab[0]; refreshSection(); }
    }, []));
  });
  host.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: 'LINE要望' }, []),
    el('p', { class: 'sub', text: '未対応を優先して確認します。' }, []),
    segmented
  ]));

  var items = state.feedback.filter(function (item) {
    if (state.feedbackFilter === 'all') { return true; }
    return state.feedbackFilter === 'open' ? item.status === 'open' : item.status === 'handled';
  });
  if (!items.length) {
    host.appendChild(el('div', { class: 'card' }, [el('p', { class: 'empty', text: '該当する要望がありません。' }, [])]));
    return;
  }
  items.forEach(function (item) {
    var card = el('div', { class: 'card' }, [
      el('div', { class: 'head' }, [
        el('h3', { text: item.user }, []),
        el('time', { text: item.date }, []),
        item.status === 'open' ? badge('未対応', 'warning') : badge('対応済み', 'active')
      ]),
      el('p', { text: item.content }, [])
    ]);
    if (item.status === 'handled') {
      card.appendChild(kv([
        ['管理メモ', item.note || '—'],
        ['対応者', item.handledBy],
        ['対応日時', item.handledAt]
      ]));
    } else {
      var note = el('textarea', { 'aria-label': '管理メモ' }, []);
      note.placeholder = '管理メモ（任意）';
      var done = el('button', { class: 'btn btn-primary', type: 'button', text: '対応済みにする' }, []);
      done.addEventListener('click', function () {
        item.status = 'handled';
        item.note = note.value.trim() || null;
        item.handledBy = 'local-admin';
        item.handledAt = nowStamp();
        logAudit('要望ステータス更新', 'feedback/' + item.id);
        toast('要望を対応済みにしました（モック）。', 'success');
        refreshSection();
      });
      card.appendChild(el('div', { class: 'field' }, [el('label', { text: '管理メモ' }, []), note]));
      card.appendChild(el('div', { class: 'btn-row' }, [done]));
    }
    host.appendChild(card);
  });
}

/* ---------- 監査ログ ---------- */
function renderAudit(host) {
  var list = el('ul', { class: 'timeline' }, []);
  state.audit.forEach(function (entry) {
    list.appendChild(el('li', {}, [
      el('div', { class: 'head' }, [
        el('time', { text: entry.at }, []),
        el('span', { class: 'action', text: entry.action }, []),
        badge(entry.result, 'active')
      ]),
      el('p', { class: 'meta', text: entry.actor + '・' + entry.target + (entry.revision ? '・rev ' + entry.revision : '') }, [])
    ]));
  });
  host.appendChild(el('div', { class: 'card' }, [
    el('h3', { text: '操作履歴' }, []),
    el('p', { class: 'sub', text: '管理操作を新しい順に表示します。' }, []),
    list
  ]));
}

/* ---------- ルーティング ---------- */
var renderers = {
  overview: renderOverview,
  users: renderUsers,
  settings: renderSettings,
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

function renderSection(target, focusHeading) {
  var host = document.getElementById('section-host');
  clearNode(host);
  host.appendChild(pageHead(sectionTitles[target], sectionMeta[target]));
  renderers[target](host);
  if (focusHeading) {
    var heading = host.querySelector('.page-head h2');
    if (heading) { heading.focus(); }
  }
}

function refreshSection() {
  renderSection(currentSectionFromHash(), false);
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
  renderSection(target, true);
}

function init() {
  document.querySelectorAll('.section-nav button').forEach(function (button) {
    button.addEventListener('click', function () { setSection(button.getAttribute('data-section')); });
  });
  window.addEventListener('hashchange', function () {
    var target = currentSectionFromHash();
    if (target !== renderedSection) { setSection(target); }
  });
  setSection(currentSectionFromHash());
}

document.addEventListener('DOMContentLoaded', init);
