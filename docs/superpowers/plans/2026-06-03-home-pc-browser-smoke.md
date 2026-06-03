# 自宅 PC ブラウザ smoke チェックリスト — `diet serve`（Web UI）

- 作成日: 2026-06-03
- 対象: PR #2 で実装された Local Web UI（FastAPI + 素 HTML/JS + 同梱 Chart.js）
- ステータス: HTTP 層 dogfood は全 PASS（MEMORY.md §4 2026-06-03）。
  **残るリスクは「JS 描画と DOM 更新」の目視のみ**。本リストはそれを最短で潰すための手順。
- 前提環境: 自宅 PC（Windows、Chrome/Edge いずれか）、`feat/fitbit-diet-cli` ブランチ、
  既存 `data/diet.db`（init 済み）。
- ★ Track B（live E2E / GCP）が**未完了でも**実施可能。`sync` ボタンだけは Track B 完了後に再検証する。

---

## 0. 起動

```bash
py -m uv run diet serve
# → diet web UI: http://127.0.0.1:8770  (Ctrl+C で停止)
```

- [ ] ターミナルに `http://127.0.0.1:8770` が表示される
- [ ] ブラウザで `http://127.0.0.1:8770/` を開く（外から `192.168.x.x:8770` は **見えなくて正解**）

---

## 1. 初期描画（10 項目）

各項目: **何を見るか** → **PASS 条件**。1 つでも fail なら DevTools Console を開いて
スクリーンショット + エラーログを採取して報告。

| # | 操作 / 確認対象 | PASS 条件 |
|---|---|---|
| 1 | ページが「白画面」「JS エラーで停止」になっていない | HTML 構造が見え、トースト領域がある |
| 2 | DevTools (F12) → Console を開く | エラー 0 件（warning は許容） |
| 3 | DevTools → Network タブ → リロード | 4xx/5xx が 0 件（`/api/day`・`/api/history`・`/api/auth/status` が 200） |
| 4 | 当日カード（運動 / 体重 / 摂取 / 収支）が描画される | 各値が `—` でなく **数値または「未取得」表示**、レイアウト崩れなし |
| 5 | 履歴グラフ（Chart.js）が `<canvas>` に描画される | 線 or バーが見える。空の canvas でない（既存 14 日分のデータがあれば必ず描画される） |
| 6 | グラフのツールチップ | 線にホバーすると日付・kcal がツールチップで出る |
| 7 | フォーム（intake +N / =N、weight）が見える | input + ボタンが配置されている |
| 8 | sync ボタン / publish ボタンが見える | ボタン要素が disabled でないこと |
| 9 | CSRF トークンが meta or hidden input に埋まっている | DevTools で `<meta name="csrf-token">` または hidden input を確認 |
| 10 | textContent ベース描画（XSS 対策）の検証 | DB に `<script>alert(1)</script>` を含む note を 1 件 intake で投入 →「`<script>...`」が**文字としてそのまま表示**される（実行されない）。検証後に削除 |

---

## 2. インタラクション smoke

| # | 操作 | 期待動作 |
|---|---|---|
| 11 | intake `+250` を送信 | トースト「+250 kcal を記録しました」、当日カード「摂取」「収支」が即時更新 |
| 12 | intake `=2100` を送信（合計上書き） | トースト OK、摂取合計が 2100 に更新 |
| 13 | intake 不正値（`abc` / `-50`）を送信 | 400 系のトーストが出る、当日カードは前値を維持 |
| 14 | weight `70.5` を送信 | トースト OK、当日カード「体重」が更新 |
| 15 | weight `0` を送信 | 400 系のトースト、値は変わらない |
| 16 | publish ボタン（HPasaneel 設定済みの場合のみ） | 成功なら「publish しました」トースト。リモート未設定なら `publish_git_failed` 等のトースト |
| 17 | sync ボタン（**Track B 完了後のみ**） | token 有り = 成功トースト + 当日カード更新。token 無し = `reauth_required` トースト |
| 18 | history 期間切替（UI にあれば） | グラフが再描画される（DOM の canvas が差し替わる or 再描画される） |
| 19 | リロード（F5） | 入力後の状態が DB から復元される（CSRF も再発行されて 1 回送信できる） |
| 20 | Ctrl+C でサーバ停止 | uvicorn が clean に停止、`Address already in use` が次回起動で出ない |

---

## 3. セキュリティ smoke（任意・短時間）

| # | 操作 | 期待動作 |
|---|---|---|
| S1 | 別マシン or 別 IP から `http://<このPCの LAN IP>:8770/` | **接続不可**（loopback バインド） |
| S2 | DevTools で `Host: evil.example` を改ざんしてリクエスト | 400 |
| S3 | DevTools で `Origin: http://evil.example` をつけて POST | 403 |
| S4 | CSRF トークン無しで POST `/api/intake` | 403 |

S1-S4 は HTTP dogfood で既に検証済み（§4 2026-06-03）。**目視は任意**。

---

## 4. 完了条件

- セクション 1（10 項目）と セクション 2 の #11-#16, #18-#20 が全 PASS
- #17（sync ボタン）は Track B 完了後に追加検証
- スクリーンショット 2 枚（初期描画、intake 後）を `docs/superpowers/qa/2026-06-03-web-ui-smoke/` に保存し、
  `MEMORY.md §4` を「自宅 PC 目視確認 PASS」で更新

## 5. fail 時の三段切り分け

1. **DevTools Console** にエラーが出ているか
2. **Network タブ** で API が 200 か（4xx/5xx ならサーバ側の問題）
3. `py -m uv run pytest` がローカルで全 green か（211 tests）

3 段全て OK なのに UI が壊れている場合は、ブラウザキャッシュを疑う（Ctrl+Shift+R で hard reload）。
