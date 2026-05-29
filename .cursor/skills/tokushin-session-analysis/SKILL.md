---
name: tokushin-session-analysis
description: >-
  SnsClub新特進の伴走セッション分析（虎の巻構成遵守・ヒアリング・9マス・Lステップ/ジョーズ連携）。
  Use when working in 新特進_セッション分析, session transcript evaluation, MG dashboard,
  roster_paste.tsv, student_profiles.csv, Lステップ Excel, コミットプラン/ジョーズ,
  structure_adherence_rate, or continuing this analysis project.
---

# 新特進 セッション分析

## プロジェクトパス

`/Users/fuka/生徒分析/新特進_セッション分析`

関連: `~/snsclub-coaching-system/prompts/`（品質評価プロンプト原本）

## ゴール

MG・運営が**誰に・なぜ・どう介入するか**を一覧で判断する。

| 観点 | データ源 | 状態 |
|------|----------|------|
| 虎の巻構成遵守 | Zoom文字起こし → Gemini | ✅ 実装済 |
| ヒアリング抽出 | 文字起こし | ✅ 実装済 |
| 伴走セッション予定 | ロスターTSV / ジョーズ | 🟡 ロスターのみ |
| 初投稿30日・SP進捗 | Lステップ Excel | 🟡 `import_lstep.py` → `lstep_progress.csv` |
| タスク達成・可処分時間 | ジョーズ（コミットプラン） | ⬜ 一部確認済 |
| 9マス（コーチャブル×目標） | 文字起こし＋ジョーズ | 🟡 CSV手入力のみ |
| VTT自動取得 | 別エンジニア → `data/inbox/` | ⬜ 未連携 |

詳細・Excel列マップ: [reference.md](reference.md)

## 評価ルール（構成遵守）

- **文言の違いはOK**（一言一句一致は不要）
- **必須パートが丸ごと欠けている = NG** → `missing`
- スコア: `structure_adherence_rate`（covered=1, partial=0.5, missing=0）
- 1回目: ブロック A1〜E1（19個）／2回目以降: 01〜07（7個）
- プロンプト: `prompts/01_structure_adherence_session1.md`, `02_*`, `03_hearing_extraction.md`

## 日次運用コマンド

```bash
cd "/Users/fuka/生徒分析/新特進_セッション分析"
source venv/bin/activate

# 文字起こしを data/inbox/{生徒ID}_{MG}_{回数}.vtt に置く
python scripts/daily_run.py          # 最大10件評価 → DB → CSV → dashboard/data.json

python scripts/import_lstep.py     # Lステップ xlsx → lstep_progress.csv
python scripts/build_dashboard.py  # UI用JSONのみ再生成
python scripts/serve_dashboard.py  # http://localhost:8765（ターミナル開いたまま）

python scripts/ingest_results.py   # 手動JSON（*_manual.json）だけDB取込
```

`.env`: `GOOGLE_AI_API_KEY`, 任意 `GEMINI_MODEL=gemini-2.0-flash`

## データ配置

| パス | 用途 |
|------|------|
| `data/inbox/` | 未処理VTT/txt |
| `data/transcripts/` | 処理済みアーカイブ |
| `data/results/*.json` | 1セッション1JSON |
| `data/master/session_analysis.db` | 蓄積本体 |
| `data/metadata/roster_paste.tsv` | スプシ生徒一覧（タブ区切り貼付） |
| `data/metadata/student_profiles.csv` | MG入力（時間・9マス・サポートメモ） |
| `data/metadata/lstep_progress.csv` | Lステップ取込（`import_lstep.py` 出力） |
| `dashboard/` | 静的UI + `data.json` |

### MG入力 CSV（`student_profiles.csv`）

`roster_name` はロスターの生徒名と一致。主要列:

- `disposable_hours_week`, `time_used_hours_week`
- `coachable_level`, `goal_level`（高・中・低 → 9マス①〜⑨）
- `first_post_date`, `mg_support_notes`
- `age`, `occupation`, `video_experience`, `has_pc`, `genre`

## ダッシュボードUI（1行の意味）

- 横バー 1〜9回目: 予定日／緑%=分析済み遵守率
- 初投稿30日 / 可処分×進捗 / 9マス / 注力フラグ
- 行クリック → MGメモ・仮説・属性・構成ブロック
- 生徒名突合: ひらがな正規化 + `@user_id` 部分一致（例: ルカ ↔ こいでるか）

## 次の実装優先（会話の続き）

1. ~~**Lステップ取込**~~ — `import_lstep.py` 実装済。要: 定期実行・初投稿データのコース突合改善
2. **ジョーズ取込** — `コミットプラン (7).xlsx` → `セッション実施状況管理`（header行=9）
3. スプシ自動書き出し / Surge公開
4. inbox への VTT 自動投入（外部）

ジョーズは `scripts/import_joes.py` を新規追加予定。`build_dashboard.py` でマージ。

## 手動評価JSON

`data/results/{student}_{session}_manual.json` も `ingest_results.py` でDB取込可。`structure` + `hearing` キーを含むこと。

## 変更時の注意

- `build_dashboard.py` 実行後にブラウザをハードリロード
- 同一 `student_id` + `session_number` はDBで上書き
- コミットはユーザー明示時のみ
