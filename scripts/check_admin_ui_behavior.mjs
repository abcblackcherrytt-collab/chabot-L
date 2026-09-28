'use strict';

const DEBUG_LIST = "http://127.0.0.1:9223/json/list";
const PAGE_URL = "http://127.0.0.1:8001/admin";

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function main() {
  const targets = await fetch(DEBUG_LIST).then((r) => r.json());
  const page = targets.find((t) => t.type === "page");
  if (!page) { throw new Error("page target not found"); }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const entry = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) { entry.reject(new Error(JSON.stringify(message.error))); }
      else { entry.resolve(message.result); }
    }
  };
  function send(method, params) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evaluate(expression) {
    const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) { throw new Error(JSON.stringify(result.exceptionDetails)); }
    return result.result.value;
  }

  await send("Page.enable");
  await send("Page.navigate", { url: PAGE_URL });
  await sleep(700);

  const checks = [];
  function record(name, ok, detail) { checks.push({ name, ok: Boolean(ok), detail }); }

  await evaluate("location.hash = 'users'");
  await sleep(200);
  await evaluate("[...document.querySelectorAll('.section-main button')].find((b) => b.textContent === '詳細').click()");
  await sleep(200);
  const detailName = await evaluate("document.querySelector('.panel h3') ? document.querySelector('.panel h3').textContent : ''");
  record("ユーザー詳細を開ける", detailName === "佐藤 花子", "詳細パネルに佐藤 花子が表示された: " + detailName);

  await evaluate("const s = document.querySelector('input[type=search]'); s.value = '高橋'; s.dispatchEvent(new Event('input', { bubbles: true }));");
  await sleep(200);
  const rowCount = await evaluate("document.querySelectorAll('.section-main tbody tr').length");
  const rowText = await evaluate("document.querySelector('.section-main tbody tr') ? document.querySelector('.section-main tbody tr').textContent : ''");
  record("表示名前方一致検索", rowCount === 1 && rowText.includes("高橋 美咲"), "「高橋」で1件: " + rowCount + "件");

  await evaluate("document.querySelector('.panel form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));");
  await sleep(200);
  const reasonError = await evaluate("document.querySelector('.panel .error-note') ? document.querySelector('.panel .error-note').textContent : ''");
  record("プラン変更の理由必須検証", reasonError.includes("必須"), "理由なし送信のエラー: " + reasonError);

  await evaluate("location.hash = 'settings'");
  await sleep(200);
  await evaluate("const i = document.querySelector('.settings-grid input[type=number]'); i.value = '0'; [...document.querySelectorAll('.settings-grid button')].find((b) => b.textContent === '下書き保存').click();");
  await sleep(200);
  const limitError = await evaluate("document.querySelector('.settings-grid .error-note') ? document.querySelector('.settings-grid .error-note').textContent : ''");
  record("上限設定の範囲検証", limitError.includes("1〜999"), "0入力のエラー: " + limitError);

  await evaluate("location.hash = 'feedback'");
  await sleep(200);
  const beforeCount = await evaluate("[...document.querySelectorAll('.segmented button')].find((b) => b.textContent.startsWith('未対応')).textContent");
  await evaluate("[...document.querySelectorAll('.section-main button')].find((b) => b.textContent === '対応済みにする').click();");
  await sleep(200);
  const afterCount = await evaluate("[...document.querySelectorAll('.segmented button')].find((b) => b.textContent.startsWith('未対応')).textContent");
  record("要望の対応済み更新", beforeCount.includes("3") && afterCount.includes("2"), "未対応 " + beforeCount + " → " + afterCount);

  await evaluate("location.hash = 'audit'");
  await sleep(200);
  const auditCount = await evaluate("document.querySelectorAll('.timeline li').length");
  const firstAction = await evaluate("document.querySelector('.timeline li .action') ? document.querySelector('.timeline li .action').textContent : ''");
  record("監査ログへの記録反映", auditCount >= 7 && firstAction.includes("要望"), "監査 " + auditCount + "件・先頭: " + firstAction);

  ws.close();
  const failed = checks.filter((c) => !c.ok);
  console.log(JSON.stringify({ checks, passed: checks.length - failed.length, failed: failed.length }, null, 2));
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
