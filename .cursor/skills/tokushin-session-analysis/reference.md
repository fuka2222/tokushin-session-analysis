# 新特進セッション分析 — 参照

## システム図（現状）

```
【入力】                         【処理】                    【出力】

VTT / txt → inbox/     ──→  evaluate_session.py  ──→  results/*.json
                              daily_run.py              ↓
roster_paste.tsv       ──→  ingest_results.py    ──→  session_analysis.db
student_profiles.csv          build_dashboard.py        ↓
                                                     dashboard/data.json
                                                     master/*.csv
                                                          ↓
                                                     serve_dashboard.py
                                                     → localhost:8765
```

## Lステップ Excel（確認済み 2026-05）

**ファイル例**: `~/Downloads/Lステップの顧客データ260525.xlsx`

| シート | 用途 |
|--------|------|
| `投稿プログラム（新）` | SP/投稿PG: `投稿プログラム開始日`, `STEP1完了日`〜`STEP19完了日`, `表示名`, `担当MG名`, `コース` |
| `投稿数` | `1投稿目完了日`〜（初投稿30日判定に使う） |
| `生徒情報` | 属性補完用 |

特進フィルタ: `コース` に `特進` を含む行。

例（こいでるか）: `STEP1完了日`=2026-04-14 〜 STEP19まで日付あり。`投稿プログラム開始日`はNaTのことあり。`1投稿目完了日`は投稿数シートで要確認。

## ジョーズ / コミットプラン Excel（確認済み）

**ファイル例**: `~/Downloads/コミットプラン (7).xlsx`

| シート | 用途 |
|--------|------|
| `セッション実施状況管理` | **ヘッダー行 index=9**。生徒名・user ID・SP開始日・1回目通常セッション・担当MG名・列`0`〜`12`（セッション日）・`合計アクション数` |
| `Lステップマスタ` | ID・表示名・SP受講開始日など |
| `アクションシート保管用` | タスク・可処分時間の候補（要再探索） |

ロスター `roster_paste.tsv` はこのシートから貼ったデータと同等構造。

## 9マス（コーチャブル度 × 目標設定度）

| | 目標:高 | 目標:中 | 目標:低 |
|--|---------|---------|---------|
| **コーチ:高** | ①ロケット | ②目的地薄い | ③他人ゴール |
| **コーチ:中** | ④ブレーキ持ち | ⑤平均前進 | ⑥受け身 |
| **コーチ:低** | ⑦我流 | ⑧防衛 | ⑨漂流 |

算出: `scripts/student_insights.py` の `nine_grid_cell(coachable, goal)`

## 可処分時間 × 進捗（4象限）

| key | 条件 | 仮説例（high_low） |
|-----|------|-------------------|
| high_high | 週≥8h & 進捗≥0.55 | — |
| high_low | 週≥8h & 進捗<0.55 | 虚偽報告、進め方不明、完璧主義、ツール、課題不明、添削ハードル |
| low_high | 週<8h & 進捗≥0.55 | 効率型 |
| low_low | 週<8h & 進捗<0.55 | 時間確保が課題 |

閾値は `student_insights.py` の `TIME_HIGH_THRESHOLD`, `PROGRESS_HIGH_THRESHOLD` で変更可。

## 初投稿30日

- 基準日: `SP開始日`（ロスター or Lステップ）
- 初投稿日: `student_profiles.first_post_date` または Lステップ `1投稿目完了日`
- 判定: `first_post_status()` in `student_insights.py`

## スクリプト一覧

| スクリプト | 役割 |
|-----------|------|
| `parse_vtt.py` | VTT→テキスト |
| `evaluate_session.py` | 1件Gemini評価 |
| `batch_evaluate.py` | 一括（--limit, --sync-db） |
| `daily_run.py` | 日次10件パイプライン |
| `ingest_results.py` | JSON→DB |
| `export_master.py` | DB→CSV |
| `build_dashboard.py` | DB+ロスター+profiles→data.json |
| `serve_dashboard.py` | :8765 |
| `student_insights.py` | 9マス・象限・初投稿・注力フラグ |
| `analyze_mg_outcomes.py` | MG遵守×成果（成果CSV要） |
| `analyze_roster_schedule.py` | ロスター頻度集計 |
| `import_lstep.py` | Lステップ xlsx → `lstep_progress.csv` |

## 検証済みサンプル

- 生徒: こいでるか / MG: 小針彩乃 / 1回目 2026-04-28
- 手動評価: `data/results/ルカ_1_manual.json` — 遵守率 0.868, high, partial 9件
- 名前突合: `ルカ`（DB）↔ `こいでるか`（ロスター）はひらがな/`@hiroruka` でマージ

## 虎の巻 1回目 必須ブロック（監査用）

A1挨拶, A2流れ, A3MG自己紹介, A4生徒自己紹介, A5傾聴家族, A6入会きっかけ, A7学習状況,
B1役割, B2初速, B3マインドセット, C1回数, C2参加ルール, C3日報,
D1目標, D2SP開始, D3目標シート, D4日程, D5タスク, D6日報時刻, E1クロージング
