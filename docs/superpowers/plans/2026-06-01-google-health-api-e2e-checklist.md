# Google Health API 移行 — Live E2E 検証チェックリスト

- 作成日: 2026-06-01
- ステータス: **2026-06-04 ステップ 1〜5 検証済み（ステップ 6 publish + 7 merge が残）**

## ★ 2026-06-04 live 検証サマリー

- ステップ 1〜2（GCP / `.env` / `diet auth`）✅ token + refresh_token 保存、identity 実 user_id 取得。
- ステップ 3（`diet sync --days 3`）✅ 体重 70.5kg（grams→kg 正常）。steps/active/distance は 0 = アカウントに該当データ無し（生レスポンス `{}` で確認、バグではない）。
- ステップ 4（ASSUMED 突合）✅ **rollup ネストのバグを発見・修正**（`value.<metric>` ではなく `<camelCaseType>.<metric>`。`totalCalories.kcalSum`=1538 を live 確認、commit `fa550d4`）。identity / weightGrams / weight civil_time filter も CONFIRMED。steps/active/distance の wrapper+metric は当アカウントにデータ無く未確認（camelCase 推定のまま）。
- ステップ 5（Renpho 体重）✅ 実体重（70.1/70.5）が Renpho→Google Health で流れている。
- 周辺バグ修正: cp932 UTF-8（`5d0d0fa`）、OAuth callback timeout 300→600s、`diet doctor` 追加（`98a6bac`）。
- 詳細は spec rev 10 の「ASSUMED → live E2E 結果」表を参照。

---

### （以下は当初手順。実行済み項目は上記サマリー参照）

- 旧ステータス: **code-complete, E2E-pending**
- 対象ブランチ: `feat/fitbit-diet-cli`
- 前提: Task 1-6 のコードは実装・commit 済み（159 tests passing）。本ドキュメントは
  GCP の実認証情報（まだ未取得）が用意でき次第、人が手動で実行する live 検証手順。
  ここに書かれた手順が **すべて pass するまで、移行は "code-complete, E2E-pending"** であり
  「動作確認済み」とは呼ばない。

---

## 1. GCP セットアップ（人手・1 回のみ）

> ★ 旧 Fitbit Developer App（`dev.fitbit.com`、`FITBIT_*` env、HTTPS 自己署名証明書）は
> rev 10 で全廃。以下は Google Cloud 側の新規セットアップ。

- [ ] **プロジェクト作成** — Google Cloud Console で新規プロジェクトを作成（または既存を選択）。
- [ ] **Google Health API を有効化** — 「API とサービス」→「ライブラリ」で *Google Health API*
      を検索して有効化。
- [ ] **OAuth 同意画面を構成し、本番（Production）に PUBLISH する。**
      ★ **重要**: 同意画面が「テスト」ステータスのままだと **refresh token が 7 日で失効**する。
      cron 運用（`diet sync`）が 7 日後に `invalid_grant` で死ぬので、必ず *In production* に
      公開すること。
- [ ] **テストユーザーを追加** — `pcjidouka@gmail.com` を OAuth 同意画面のテストユーザーに登録
      （公開審査が完了するまでの間のアクセス用）。
- [ ] **OAuth クライアント作成** — 認証情報 → 「OAuth クライアント ID を作成」→
      アプリケーションの種類は **ウェブ アプリケーション（Web application）**。
- [ ] **リダイレクト URI を登録** — `http://localhost:8765/callback`
      （PLAIN HTTP の loopback。証明書は不要）。
- [ ] **`.env` を記入** — プロジェクトルートの `.env` に以下を設定:
      - `GOOGLE_CLIENT_ID=...`
      - `GOOGLE_CLIENT_SECRET=...`
      - `GOOGLE_REDIRECT_URI=http://localhost:8765/callback`

---

## 2. 認証フロー（`diet auth`）

- [ ] `py -m uv run diet auth` を実行。
- [ ] ブラウザが開き Google の認可画面が表示される → 認可する。
- [ ] **証明書プロンプトが出ないこと**を確認（標準 Google OAuth 2.0 + PLAIN HTTP loopback なので
      自己署名証明書の警告は一切出ないのが正しい）。
- [ ] トークンが DB（`data/diet.db` の `fitbit_token` テーブル）に保存される。
- [ ] これで確認できること: loopback callback サーバー（`localhost:8765`）+ token 交換
      （`/token`）+ identity エンドポイント（`GET /users/me/identity`）の 3 つが機能している。

---

## 3. データ同期（`diet sync --days 3`）

- [ ] `py -m uv run diet sync --days 3` を実行。
- [ ] `data/diet.db` を SQLite で開いて中身を検査:
      - [ ] `daily_activity.steps` が populated（歩数が入っている）。
      - [ ] `daily_activity.active_energy_kcal` が populated（運動消費・BMR フリー）。
      - [ ] `daily_activity.distance_km` が populated。
      - [ ] `daily_weight.weight_kg` が **正気な値（SANE）** — 例えば 70 前後であって
            **70000 のような 1000 倍ではない**こと。1000 倍なら grams→kg 変換が壊れているサイン
            （client は `weightGrams / 1000.0` を期待）。

---

## 4. ★ ASSUMED フィールドの実レスポンス突合（最大の残リスク）

> これが live 検証で唯一の実質的リスク。各項目は `src/diet/google_health_client.py`（または
> `oauth.py`）の **1 行のアダプタ**に対応する。実レスポンスと食い違っていたら、その 1 行を直し、
> 対応するユニットテストの fixture も同時に直す（テスト 1 本 + 本体 1 行）。

実レスポンス（`diet sync` 実行時のログ、または curl での直接叩き）を確認し、以下の **ASSUMED**
キー名・単位・構造が正しいか突合する:

- [ ] **distance ロールアップの値キー** = `meterSum`、かつ単位が **メートル**であること
      （`google_health_client.py:71`。`get_daily_distance_km` は `value / 1000.0` で km 化）。
- [ ] **total-calories ロールアップの値キー** = `kcalSum` であること
      （`google_health_client.py:67`。`get_daily_total_calories_kcal`）。
- [ ] **identity レスポンス** が `healthUserId`（無ければ `legacyUserId`）を返すこと
      （`oauth.py:92`。`fetch_user_id`）。どちらも無い場合のみ `"me"` フォールバック。
- [ ] **weight のフィルタフィールド** = `weight.sample_time.civil_time` であること
      （`google_health_client.py:77-79`。civil_time の範囲フィルタで対象日を絞っている）。
- [ ] **ロールアップの `value` が直接キーされている**こと
      = `value.countSum`（**`value.steps.countSum` ではない**）
      （`google_health_client.py:50-56`。`_daily_rollup_value` は `points[0]["value"][value_key]`
      を直読みする）。これが入れ子（`value.steps.countSum`）だった場合、steps/active-energy/
      total-calories/distance の **4 つすべて**が `None`→0 に潰れるので、最初に疑う。

> 既に CONFIRMED（変更不要）: `steps` の `countSum`、`active-energy-burned` の `kcalSum`、
> `weight` の `weightGrams`。

---

## 5. Renpho → Fitbit → Google Health の体重経路確認

- [ ] Google Health 側にこのアカウントの **Renpho 計測体重が実際に出現している**ことを確認。
- [ ] ★ この多段経路（Renpho アプリ →（サードパーティ連携）→ Fitbit `body/weight` →（同期）→
      Google Health `weight` data type）は **設計上の想定であって未検証**。
      実際に流れているか必ず目視確認する。
- [ ] 流れていない場合は `py -m uv run diet weight 71.2`（`--date` 指定可）の手動入力で代替できる
      ことを確認。

---

## 6. エンドツーエンド（`diet` フル + publish）

- [ ] `py -m uv run diet` を実行し、5 ステップの対話フローを最後まで通す
      （Google Health 同期 → 食事入力 → BMR/収支 → publish）。
- [ ] HPasaneel ダッシュボードに publish される。
- [ ] ダッシュボードに **歩数 / 距離 / 運動（exercise_kcal = active_energy）/ 体重**が
      表示されることを確認。
- [ ] ★ **プライバシー境界**: 公開された `log.json` に **食事メモ（note）/ 摂取 kcal が
      含まれていない**ことを確認（`build_records_from_db` は `daily_activity` と `daily_weight`
      しか SELECT しない設計。`intake_events` / `config` / `fitbit_token` には触れない）。
- [ ] 参考: `total_calories_kcal` は診断専用で公開されない（BMR 二重計上防止のため）。

---

## 7. 完了条件

- 上記 1-6 がすべて pass するまで、本移行は **"code-complete, E2E-pending"** とする。
- pass 後、spec（`docs/superpowers/specs/2026-05-25-fitbit-diet-design.md` rev 10）の
  「一部 API フィールドは live E2E 未検証」記述と、本チェックリストのステータスを
  「検証済み」に更新する。
- ASSUMED フィールドのいずれかを live で修正した場合は、その差分を spec rev 10 amendment と
  `MEMORY.md` に記録する。
