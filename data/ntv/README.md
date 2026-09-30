# 日テレ放送データの運用

`src/data/episodes.json` にWikipedia由来の元の1,376件と、2026-07-27以降の追加分をまとめて保存します。更新スクリプトは元の行の内容・順序をハッシュで確認し、その後ろに追加データを追記します。追加行の企画ID（`projectId`）で更新対象を識別します。
出演者は予告の企画欄から取得し、その企画の各国に同じ一覧を紐付けます。個々の出演者と訪問国の対応を表すものではありません。

## 実行

Python 3.10以上の標準ライブラリのみを使います。環境変数 `OPENAI_API_KEY` にAPIキーを設定します。キーはファイルやログに保存しません。

```bash
python3 scripts/update-ntv.py
# リポジトリのデータを変更せず検証
python3 scripts/update-ntv.py --output-dir /tmp/ntv-review
# 通信なしで再現。未保存のAPI回答は保留となります。
python3 scripts/update-ntv.py --input .cache/ntv/articles.json --offline --output-dir /tmp/ntv-review
python3 scripts/update-ntv.py --validate-only
python3 -m unittest discover -s scripts/tests -v
```

`--today` で日付境界を固定できます。未来の放送は公開せず、対象期間外や取得できなくなった企画の既存データも保持します。

## 資料の特定と国の取得

1. [日テレの記事JSON](https://www.ntv.co.jp/q/articles.json)から `○月○日の「イッテQ」は` という予告タイトルを選び、HTMLの見出しで企画を分割します。放送日・企画名・出演者・本文・URLはAIを使わず取得します。
2. 総集編・アワード等の見出しは除外します。日付・出演者が欠けた企画は保留します。
3. 見出し末尾の `in 地名` が全て一意に解釈できれば辞書で国を取得します。本文だけにある追加の訪問先は、この経路では補完しません。
4. 見出しで取得できなければ、予告本文と同日の参考資料候補をOpenAIに一度だけ送ります。参考資料は、`OAまとめ` タグの記事、[日本海テレビ番組表](https://www.nkt-tv.co.jp/program/)のイッテQ詳細リンク、保存済み番組表、手動追加資料です。番組表は番組名・放送日・夕方以降の時間帯・再放送でないことを検査します。
5. OAまとめは公開日が放送日と同じ記事を候補にします。**公開日は放送日や対象企画との一致を保証しません。** 入力には候補であることを示し、別企画の資料を使わないよう指示します。公開が遅れた記事は自動対応できないため、`references.json` で放送日・企画IDを指定できます。過去の番組表の取得も保証しません。
6. OpenAI Responses API（`gpt-6-sol`）が `{"countries":["FI"]}` のJSONを返します。都市・地域の国への変換と対象企画との対応もこの呼び出しで判断します。応答の意味は信頼し、独自の正解ラベルやconfidenceによる採用条件は設けません。JSONの構造・国コード、不完全応答・拒否だけを検査します。

## 差分更新

- `generated/decisions.json` に入力資料・判定・入力ハッシュを保存します。同じ入力の処理済み企画は、APIキャッシュがなくても再照会しません。
- 新規企画・本文の変更・参考資料の追加や変更・判定方針の変更は再処理します。
- 正常な空配列も処理済みです。資料が変わるまで再照会しません。
- 再処理に成功した場合は、企画の国リスト全体を置き換えます。以前の国だけを残すことはありません。
- APIエラーは保留として記録し、以前の訪問記録を保持して次回再試行します。エラー応答はキャッシュしません。
- 記事内の企画追加・削除・順序や見出し変更によって企画IDの意味が変わる場合は、`article_structure_changed` で保留します。
- API回答は `.cache/ntv/openai/`、使用回数・使用量は `.cache/ntv/run.json` に保存します。429・一時的な5xx・通信失敗は最大3試行、APIの各試行は90秒でタイムアウトします。

## 辞書と手動訂正

`places.json` は国・地域・都道府県、`cities.json` はGeoNames由来の都市・別名を保持します。ハワイ・アラスカはUS、ドバイはAEです。同名都市の国が複数あれば辞書で決めずOpenAIへ送ります。未収録の都市名もOpenAIの対象です。

辞書の更新は `python3 scripts/import-geonames.py` で行い、週次処理では更新しません。
出典: [GeoNames](https://www.geonames.org/)、[cities15000.zip](https://download.geonames.org/export/dump/cities15000.zip)。ライセンス: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。元ZIPのハッシュ、表記の選別・同名都市の国候補統合をJSONに記録しています。

`references.json` に資料を追加できます。番組表詳細URLだけなら自動取得し、OAまとめ等を追加する場合は `text` を指定します。

```json
[{"date":"2026-02-15","projectId":"xb8d5pluwyejoiic:1","url":"https://www.nkt-tv.co.jp/program/detail.php?date=260215&no=22"}]
```

`overrides.json` は企画IDをキーにした手動訂正です。

```json
{
  "xb8d5pluwyejoiic:1": {
    "status":"accepted",
    "countries":["FI"],
    "evidence":{"text":"根拠となる記述","url":"https://www.ntv.co.jp/q/articles/304vz64ropvjndaqetd.html"}
  }
}
```

`status: pending` は保留、`status: excluded` は削除です。記事の構造変更後に同じIDを再利用する場合は、対応を確認して `allowIdentityChange: true` と国・根拠を指定します。

## GitHub Actions

日曜23:00 JSTと手動実行で、`automation/ntv-data` ブランチの確認用PRを作成・更新します。自動マージはしません。Secretsの `OPENAI_API_KEY` と、Settings → Actions → GeneralのPR作成許可を使います。

未マージのデータPRと前回成功時の資料・APIキャッシュを復元します。旧形式の別ファイルにある追加データも共通ファイルへ移行します。mainとデータPRの双方で同じ生成ファイルが変わった場合は停止します。処理済み判定はPRに保存するため、90日保持のキャッシュartifactが失効しても再照会を防げます。

テスト・データ検証・lint・buildが通った後にPRを作成します。通常は `GITHUB_TOKEN` を使います。PRの別ワークフローも起動する場合は限定権限の `NTV_PR_TOKEN` を設定します。ActionsのSummaryと生成レポートで、保留理由・資料URL・API回数を確認できます。
