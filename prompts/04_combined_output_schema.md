# 統合評価の出力スキーマ

`evaluate_session.py` は構成遵守とヒアリング抽出を1回のAPI呼び出しで実行する場合、以下のJSONを返すようプロンプトを結合する。

```json
{
  "structure": { /* 01 or 02 の structure オブジェクト */ },
  "hearing": { /* 03 の hearing オブジェクト */ },
  "evaluated_at": "ISO8601"
}
```

バッチ処理・相関分析は `data/results/{student_id}_{session}.json` に保存する。
