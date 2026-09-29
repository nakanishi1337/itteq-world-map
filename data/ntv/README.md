# 日テレ放送データの運用

既存の `src/data/episodes.json` は固定し、更新候補は `src/data/episodes-ntv.json` に保存します。
出演者と訪問国は**企画単位**です。日テレの企画欄の出演者全員を、その企画で採用した各国に紐付けます。
個々の出演者が全ての国へ実際に行ったことを確認したデータではありません。

## 実行

Python 3.10以上・標準ライブラリのみを使用します。

```bash
# 2026-07-27以降を処理。元のWikipediaデータは変更しません。
python3 scripts/update-ntv.py
# 検証用の別ディレクトリへ出力
python3 scripts/update-ntv.py --output-dir /tmp/ntv-review
# 保存済み資料で再現（APIキーがあればJevの呼び出しは行います）
python3 scripts/update-ntv.py --input .cache/ntv/articles.json --offline --output-dir /tmp/ntv-review
# 日付境界も固定して再現
python3 scripts/update-ntv.py --input .cache/ntv/articles.json --offline --today 2026-09-29 --output-dir /tmp/ntv-review
python3 -m unittest discover -s scripts/tests -v
```

`--offline` は記事取得を止めるオプションです。完全にネットワークを使わない検証では
`TYPESAFE_API_KEY` を設定せずに実行してください。保存済みのJev応答があれば再利用します。
`--since` は初回・追加取得の対象を制限し、過去の確定記録を削除しません。

## 判定の順序

1. 企画名の総集編・アワード表記は新しい訪問として除外。
2. 見出し末尾の `in 地名` が**全て**一意に解釈できれば辞書で確定。
3. それ以外は日テレの本文、同日のOAまとめ、保存済みの日本海テレビ番組表を候補にする。
4. OAまとめは正規化した企画名で対応付け。異なる表記はJevで同じ企画か判定する。
5. Jevが地名候補ごとに今回の訪問かを判断し、入力行から根拠を選ぶ。
6. confidence 0.90以上で根拠があり、残る候補にも未解決がなければ採用候補。
   記事間の矛盾・API障害・未知地名・予告欠落などは保留。

見出し優先のため、見出しで確定した企画の本文にしかない追加訪問先は補完しません。
同日の別企画の国を混ぜないよう、対象企画を指定して判定します。
公開日だけで記事の対応を確定しません。未来の放送日は資料を保存しても公開しません。
予告そのものがない放送は出演者を推測せず、`missingPreviews` に報告します。

## 都市・地域の辞書

- `places.json`: 国、都道府県、ハワイ・アラスカなどの地域とコードの対応。
- `cities.json`: GeoNamesの人口15,000人以上の都市・首都のスナップショット。
  取り込んだ版は34,148都市、48,950表記。都市の基本名・ASCII名・かなを含む別名、
  日本国内の漢字名を収録します。言語ラベル付きの日本語辞書ではありません。
- 同名の英語都市名を持つ別都市の国候補も共有し、ロンドンやバンクーバーなどを
  特定の国に決め打ちしません。保守的な処理のため、フィレンツェなど日本語では
  区別される名前でも複数国候補となる場合があります。
- 全都市・集落・島を網羅するものではありません。未知の見出し地名は原文を残して保留。
  本文にある辞書未収録地名の網羅的な検出は保証しません。

更新は次のコマンドで行い、通常のコードPRとして内容を確認します。週次CIでは更新しません。

```bash
python3 scripts/import-geonames.py
# 同じ入力ZIPで完全に再現する場合
python3 scripts/import-geonames.py --zip /path/to/cities15000.zip
```

出典: [GeoNames](https://www.geonames.org/)、[cities15000.zip](https://download.geonames.org/export/dump/cities15000.zip)。
ライセンス: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。
地名の抽出・表記の選別・同名都市の国候補統合を行っています。元ZIPのSHA-256はJSONに記録します。

## Jevの評価と有効化

モデルは `jev-1.13.0` に固定。APIキーは環境変数 `TYPESAFE_API_KEY` に設定します。
キーをリポジトリやJSONへ保存しないでください。

```bash
# 実APIで評価。合格時のみ証明を更新し、週次処理でJevの採用を有効化
python3 scripts/evaluate-ntv.py --certify
```

2026年44企画を開発用、2025年11企画を別の確認用データとし、
`ntv-gold.json` に資料で確認できる国を記録しています。
ラベルの対象資料は予告本文です。フィンランドの例だけは明示的にOAまとめと番組表も
評価入力に含めます。実際の全訪問先を網羅した正解データとは区別してください。
単体テストの偽APIは入出力と制御を検証するもので、Jevの日本語理解の検証ではありません。

評価は適合率・再現率・保留率・API使用量を出力します。誤採用ゼロ、フィンランドの
補完成功、Jevによる採用があることを合格条件とします。
APIキー未設定は終了コード2（未検証）、基準未達は1。未検証時に合格を捏造しません。
`evaluation.json` をマージしてから週次更新を有効化してください。
判定コード・辞書・モデル・プロンプトを変更すると証明のハッシュが一致しなくなるため、
再評価が必要です。confidenceは正答率ではありません。

## 手動補完・訂正

`references.json` は配列です。日本海テレビの詳細URLなら本文を取得できます。
過去の番組表一覧がなくても、既知の詳細URLで参照できます。

```json
[{"date":"2026-02-15","projectId":"xb8d5pluwyejoiic:1","url":"https://www.nkt-tv.co.jp/program/detail.php?date=260215&no=22"}]
```

他のサイトの記事は自動収集せず、同じ形式に `text` を加えて対象企画の根拠を明示します。
日テレのOAまとめは通常自動収集されます。

`overrides.json` は企画IDをキーとしたオブジェクトです。

```json
{
  "xb8d5pluwyejoiic:1": {
    "status": "accepted",
    "countries": ["FI"],
    "evidence": {"text":"根拠となる記述", "url":"https://www.ntv.co.jp/q/articles/304vz64ropvjndaqetd.html"}
  }
}
```

`status: pending` で保留、`status: excluded` で明示的に削除できます。
記事の並び替え・見出しの変更は `article_structure_changed` として止めます。
対応を確認して同じIDを再利用する場合は、その手動設定に `allowIdentityChange: true` を
指定し、`accepted` の国と根拠も登録します。IDが変わった場合は旧IDをexcluded、新IDをacceptedにします。
欠落記事や再判定失敗だけでは、以前の確定値を消しません。

## GitHub Actions

- 日曜23:00 JSTと手動実行。初回から2026-07-27以降の新規・変更・保留を検査。
- Secretsへ `TYPESAFE_API_KEY` を登録。Settings → Actions → Generalで
  ワークフローによるPR作成を許可します。
- `automation/ntv-data` ブランチの確認用PRを作成・更新。自動マージしません。
- 通常は `GITHUB_TOKEN` を利用します。このトークンが作るPRでは別のPRワークフローは
  自動起動しないため、作成前に本ワークフロー内でテスト・lint・buildを実行します。
  PR側の必須チェックを別途起動する必要がある場合は、限定権限の `NTV_PR_TOKEN` を設定します。
- 既存の更新PRの生成データを復元し、最新mainのコードで再計算します。
  mainと未マージPRの双方で同じ生成ファイルが変わった場合は停止し、勝手に上書きしません。
- API応答・取得資料は90日保持のartifactに保存。採用根拠は生成JSONに残します。
  `.cache/ntv/run.json` とActionsのSummaryにAPI回数・使用量を記録します。
- 1実行200回までのJev評価呼び出し。通信は30秒timeout、最大3試行。
  429・529・一時的な5xxは再試行。上限や障害は対象企画の保留として報告します。
- 初回のコミット・push・Actionsの有効化・Secrets登録はこの実装には含めていません。
