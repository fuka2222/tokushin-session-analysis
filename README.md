# 新特進 伴走セッション分析

Zoom文字起こし（VTT）から、**虎の巻トークスクリプトの構成遵守度**と**ヒアリング項目**を抽出し、MGごとに「型をきちんと伝えられている確率」と**生徒の成果**の相関を分析するプロジェクトです。

## 分析の問い

1. **構成乖離**: 型（虎の巻）の**パート構成**は伝わっているか？（表現のニュアンス差は許容、パート欠落はNG）
2. **ヒアリング把握**: 画像のキャプチャ項目は、セッション内ヒアリングで把握できているか？
3. **MG × 成果**: 構成遵守度が高いMGの担当生徒は、投稿数・ステップ進捗などでどう違うか？

## ディレクトリ構成

```
新特進_セッション分析/
├── prompts/                    # Gemini用プロンプト
├── scripts/
│   ├── daily_run.py            # ★ 日次バッチ（10件/日想定）
│   ├── ingest_results.py       # JSON → DB取り込み
│   ├── export_master.py        # DB → マスタCSV
│   ├── evaluate_session.py     # 1件評価
│   └── ...
├── data/
│   ├── inbox/                  # ★ 毎日ここに未処理ファイルを入れる
│   ├── transcripts/            # 処理済み文字起こし（アーカイブ）
│   ├── results/                # 評価JSON（1セッション1ファイル）
│   ├── master/                 # ★ 蓄積DB + スプレッドシート用CSV
│   │   ├── session_analysis.db
│   │   ├── sessions_evaluations.csv
│   │   ├── hearing_wide.csv
│   │   ├── mg_adherence_summary.csv
│   │   └── daily_evaluation_counts.csv
│   ├── metadata/sessions.csv
│   ├── outcomes/student_outcomes.csv
│   └── logs/                   # 日次実行ログ
└── ...
```

既存の詳細評価プロンプトは [`snsclub-coaching-system`](../../snsclub-coaching-system) の `prompts/01_session_quality_evaluation.md` 等を併用できます。本プロジェクトは**構成遵守**と**ヒアリング抽出**に特化しています。

## セットアップ

```bash
cd "/Users/fuka/生徒分析/新特進_セッション分析"
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env に GOOGLE_AI_API_KEY を設定
```

## 日次運用（1日10件の蓄積）

### 毎日の流れ

1. 文字起こしを `data/inbox/` に置く（VTT または txt、1日最大10件想定）
2. 必要なら `data/metadata/sessions.csv` に行を追加
3. 日次バッチを実行

```bash
source venv/bin/activate
python scripts/daily_run.py          # 未処理を最大10件評価 → DB → CSV
python scripts/daily_run.py --limit 10 --delay 2   # 明示指定
```

4. スプレッドシート連携する場合は `data/master/*.csv` をインポート（または同期）

### 手動評価・貼り付け文字起こしの場合

Geminiを使わず分析した JSON（例: `ルカ_1_manual.json`）も同じDBに載せられます:

```bash
python scripts/ingest_results.py
```

### 蓄積データの見方

| ファイル | 内容 |
|----------|------|
| `master/session_analysis.db` | 全セッションの本体（SQLite） |
| `master/sessions_evaluations.csv` | 構成遵守率・MG・欠落ブロック一覧 |
| `master/hearing_wide.csv` | ヒアリング項目（横持ち、スプシ向け） |
| `master/mg_adherence_summary.csv` | MG別の平均遵守率（初回など） |
| `master/daily_evaluation_counts.csv` | 日ごとの処理件数 |

同一の `student_id` + `session_number` は **上書き更新**（再評価しても重複しない）。

---

## 使い方（個別）

### 1. ファイルを配置

ファイル名の推奨形式: `{生徒ID}_{MG名}_{セッション番号}.vtt`  
例: `S001_山田_1.vtt` / `ルカ_小針_1.txt`

未処理は `data/inbox/`、処理後は自動で `data/transcripts/` に移動（`daily_run.py`）。

### 2. メタデータ（任意だが相関分析に必要）

`data/metadata/sessions.csv` に以下を記入:

| 列 | 説明 |
|----|------|
| student_id | 生徒ID |
| mg_name | MG名 |
| session_number | 1〜12 |
| session_date | YYYY-MM-DD |
| sp_start_date | スタータープログラム開始日 |
| step_at_assign | アサイン時のステップ |
| step_at_session | セッション時点のステップ（事後に更新可） |

文字起こしだけでは分からない項目（SP開始から何日目、ジャンルなど）はここまたは成果CSVと結合します。

### 3. 1件評価

```bash
python scripts/evaluate_session.py \
  --vtt data/transcripts/S001_山田_1.vtt \
  --session 1 \
  --student-id S001 \
  --mg-name 山田
```

### 4. 一括評価

```bash
python scripts/batch_evaluate.py --input-dir data/transcripts
```

### 5. MG × 成果の相関

成果データ（投稿数・初投稿日・ステップなど）を `data/outcomes/student_outcomes.csv` に用意し:

```bash
python scripts/analyze_mg_outcomes.py \
  --results-dir data/results \
  --outcomes data/outcomes/student_outcomes.csv \
  --metadata data/metadata/sessions.csv
```

出力: `data/results/mg_adherence_vs_outcomes.csv` と簡易レポート（標準出力）

## 評価の考え方

| 観点 | 許容 | NG |
|------|------|-----|
| 文言 | スクリプトと違う言い回し・省略 | — |
| 構成 | パートの趣旨が別手段でカバーされている | **必須パートが丸ごと欠けている** |
| スコア | `structure_adherence_rate` = 必須パートの `covered` 率 | `missing_blocks` に必須パート名を列挙 |

「トークスクリプトをきちんと伝えられている確率が高いMG」は、例えば **初回セッションの `structure_adherence_rate` 中央値が 0.85 以上** など閾値で定義し、`analyze_mg_outcomes.py` の `--mg-threshold` で変更できます。

## ヒアリング項目（キャプチャ）

プロンプト `03_hearing_extraction.md` で文字起こしから抽出を試みます。取得可否は `confidence`（high / medium / low / not_mentioned）で記録します。

- 家族構成、ジャンル、年齢、職業、コンピューター慣れ
- 1回目の納得度、入会きっかけ・想い
- アサイン時ステップ、セッション時点ステップ（メタデータと突合）
- SP開始からの経過日数（メタデータ計算）
- セッション前の時間確保、仕事との両立、前後の変化

## 分析ダッシュボード（ブラウザで一覧）

AIドリル管理画面のように、**生徒1行＝予定・分析が一目でわかる**UIです。

```bash
python scripts/import_lstep.py      # ~/Downloads/Lステップ*.xlsx → lstep_progress.csv
python scripts/build_dashboard.py   # ロスター + 評価DB + Lステップ → data.json
python scripts/serve_dashboard.py   # http://localhost:8765
```

| 表示 | 意味 |
|------|------|
| 横並びの小バー（1〜9回目） | 伴走セッション予定日。緑=分析済み遵守率 / 青=実施済 / 灰=予定のみ |
| オレンジ「全体」バー | 分析済みセッションの平均・構成遵守率 |
| タグ | クラス / 担当MG / ジャンル |
| 詳細 | 構成ブロック・ヒアリング |

ロスターは `data/metadata/roster_paste.tsv`（スプシからタブ区切りで貼り付け可）。日次バッチ後は自動で `build_dashboard` が走ります。

### MGが入力する項目（`data/metadata/student_profiles.csv`）

| 列 | 内容 |
|----|------|
| roster_name | ロスターの生徒名と一致 |
| disposable_hours_week | 週あたり可処分時間（時間） |
| time_used_hours_week | そのうちSnsClubに使えた時間 |
| coachable_level / goal_level | 高・中・低 → 9マス①〜⑨ |
| first_post_date | 初投稿日（YYYY-MM-DD） |
| mg_support_notes | MGが主体的に行ったサポート |
| age, occupation, video_experience, has_pc, genre | 属性 |

詳細設計: `docs/dashboard_design.md`

---

## 関連リポジトリ

- 品質評価（7軸・100点）: `04_投稿数分析/coaching-evaluation-system`
- プロンプト設計の原本: `snsclub-coaching-system/prompts/`
- VTT取得パイプライン: `03_AI agent100`
