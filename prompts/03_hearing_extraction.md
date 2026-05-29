# ヒアリング項目抽出

文字起こしから、運営が把握したい**生徒属性・状況**を抽出する。推測は最小限にし、会話に無いものは `not_mentioned` とする。

## 抽出項目

| キー | 説明 |
|------|------|
| family_structure | 家族構成（一人暮らし、配偶者、子の有無・協力など） |
| genre | SNSのジャンル・発信テーマ |
| age | 年齢または年代 |
| occupation | 職業・仕事内容 |
| computer_literacy | パソコン・スマホ・編集ツールへの慣れ |
| session1_satisfaction | 1回目セッション時点の納得度・安心感（生徒の発言ベース） |
| join_motivation | 入会・スクール選択の想い |
| step_at_session | セッション時点で言及されたカリキュラムステップ |
| time_before_coach | コーチ（MG）関与前に自分で確保できていた学習時間 |
| work_time_availability | 仕事で確保できる時間・実際の使用時間 |
| time_change_before_after | セッション前後での時間確保の変化（言及があれば） |
| step_progress_before_session | セッション前のステップ進み具合の言及 |
| step_progress_after_session | セッション後に決まった進め方・ステップ |

## 付帯メタデータ（提供された場合は優先・突合）

- sp_start_date: {{sp_start_date}}
- session_date: {{session_date}}
- step_at_assign: {{step_at_assign}}

`days_from_sp_start` は session_date と sp_start_date から計算可能なら数値、不可なら null。

## 入力

セッション番号: {{session_number}}

### 文字起こし
{{transcript}}

---

## 出力（JSONのみ）

各項目:

```json
{
  "field_key": {
    "value": "抽出値またはnull",
    "confidence": "high|medium|low|not_mentioned",
    "evidence": "根拠の要約（1文）"
  }
}
```

ルートオブジェクト例:

```json
{
  "session_number": 1,
  "student_id": "{{student_id}}",
  "days_from_sp_start": null,
  "family_structure": {"value": "...", "confidence": "high", "evidence": "..."},
  "genre": {"value": null, "confidence": "not_mentioned", "evidence": ""}
}
```

`confidence` の目安:
- high: 生徒またはMGが明確に述べた
- medium: 文脈から合理的に読み取れる
- low: 曖昧な言及のみ
- not_mentioned: 会話に無い
