# イッテQ 世界地図

「世界の果てまでイッテQ!」で訪れたことのある国を、世界地図上で色付き表示する静的Webサイトです。

Wikipediaの放送リストから取得した訪問国に、公式予告・番組表・OAまとめから取得した新しい訪問データを追加して表示します。

## 公開サイト

https://itteq-world-map.nakanishi1337.workers.dev/

## 開発

Node.js 20以上を推奨します。

```bash
npm install
npm run dev
```

本番用ビルドは `npm run build`、ローカル確認は `npm run preview` で行えます。

## データの追加

訪問情報は `src/data/episodes.json` に企画・訪問国単位で保存します。国コードには ISO 3166-1 alpha-2 を使います。

Wikipediaの「放送リスト」からデータを再生成する場合は次を実行します。

```bash
python3 scripts/collect-data.py --output /tmp/wikipedia-episodes.json
```

取得元の記載内容や表記揺れを含むため、実際の訪問履歴の完全性・正確性を保証するものではありません。

## Cloudflare Workers

- Build command: `npm run build`
- Build output directory: `dist`

バックエンドや環境変数は不要です。

## 公式予告データの抽出（AI不使用）

Python 3.10以上の標準ライブラリだけで、公式ページが利用する
[記事JSON](https://www.ntv.co.jp/q/articles.json)から予告を企画単位で抽出します。
既存のWikipediaデータへのマージやアプリへの反映は行いません。

```bash
# 標準出力へJSON、標準エラーへ集計・警告
python3 scripts/collect-ntv-previews.py
# 放送日で絞り込み、別ファイルへ保存
python3 scripts/collect-ntv-previews.py --since 2026-07-27 --output /tmp/ntv-previews.json
# 保存済みの公式記事JSONで再検証（抽出結果JSONとは形式が異なります）
python3 scripts/collect-ntv-previews.py --input /tmp/ntv-articles.json
python3 -m unittest discover -s scripts/tests -v
```

出力の `records` は企画ごとの `articleId`、`projectIndex`、`source`、
`publishedAt`、`date`、`project`、`performers`、`countryCandidates`、
`body`、`evidenceText`、`reviewReasons` を持ちます。
出演者一覧は団体名・所属表記を維持します。国・地域候補にはコード、原文表記、
`evidenceText` 内の一致位置（Python文字列の開始・終了インデックス）を保存します。
記事単位の解析問題は `articleIssues` に理由・原文とともに残します。
放送日不明の企画は `--since` 指定時も要確認として保持します。

これは**予告の抽出結果であり、放送実績や訪問実績を保証するデータではありません**。
出演者一覧と国候補一覧の対応は未確定です。全出演者と全国候補の組み合わせを
訪問記録として登録しないでください。本文中の比較・過去の訪問への言及も国候補に
含まれ得ます。都市名や国内地名から国を推測せず、辞書にない名称や複合語は
取りこぼす場合があります。国候補や出演者欄がない企画も削除せず原文を残します。
`スタジオ出演者` は現地出演者と混同しないよう通常の出演者欄としては抽出しません。
警告がなくても、訪問記録として確定したことを意味しません。

`src/data` 配下への出力は拒否します。通信・入力形式・解析の異常時は既存の
出力を保持し、正常時のみ一時ファイルから置き換えます。同一入力の再実行で
結果は安定しますが、出力は毎回のスナップショットです。過去の抽出結果への
追記・統合、定期実行の設定は含みません。

### 検証結果（2026年9月29日）

- 公式JSONの806記事中、予告273記事から510企画を抽出。
- 放送日の範囲は2019年6月30日〜2026年9月20日。全期間の網羅性は未保証。
- 放送日・企画名の欠落0件、記事単位の解析問題0件。
- 通常の出演者欄なし28企画、国候補なし178企画、いずれかの警告あり190企画。
  国内ロケ、総集編、スタジオ出演者のみの記載なども含みます。
- 実記事の抜粋を使ったテストを含む7テストが成功。元記事URLはfixtureの
  `content_id` と `item_id` から復元でき、抽出結果にも保存されます。
- 既存 `src/data/episodes.json` は変更なし（SHA-256:
  `e5652af28e6f81d8ab45a654207aa23933ff6f9888aff4e2047ad1778f5dcbcc`）。

## 公式資料とOpenAIによる週次更新

`python3 scripts/update-ntv.py` で予告を静的に取得します。
企画見出しの地名で国を取得できない場合は、予告本文・同日の番組表・OAまとめを
OpenAI APIへ送り、国コードのJSONを取得します。都市・地域表記にも対応します。

追加分も `src/data/episodes.json` に追記し、アプリと週次更新が同じファイルを使います。
Wikipedia由来の元の1,376件は内容と順序を保持します。
処理済みの資料は再照会せず、変更時には企画の国リストを置き換えます。
API失敗時は既存の記録を保持し、次回に再試行します。
日曜23時JSTのGitHub Actionsで検証後にmainへ自動コミット・pushします。
設定・資料の対応付け・手動訂正は [運用手順](data/ntv/README.md) を参照してください。
