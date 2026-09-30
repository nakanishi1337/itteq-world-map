# イッテQ 世界地図

「世界の果てまでイッテQ!」で訪れたことのある国を、世界地図上で色付き表示する静的Webサイトです。

Wikipediaの放送リストから取得した訪問国に、公式予告・番組表・OAまとめから取得した新しい訪問データを追加して表示します。

## 公開サイト

https://itteq-world-map.nakanishi1337.workers.dev/

## 開発

CIと同じNode.js 22での開発を推奨します。

```bash
npm install
npm run dev
```

本番用ビルドは `npm run build`、ローカル確認は `npm run preview` で行えます。

## データの追加

訪問情報は `src/data/episodes.json` に企画・訪問国単位で保存します。国コードには ISO 3166-1 alpha-2 を使います（コソボは慣用コード `XK`）。

現在の更新は、下記の公式資料による週次更新を使います。`scripts/collect-data.py` は旧Wikipediaデータの取得用で、現在の記事からの再取得は保証しません。検証用に残しており、実行時は `--output /tmp/wikipedia-episodes.json` のように別の出力先を指定します。`src/data` への出力はできません。

取得元の記載内容や表記揺れを含むため、実際の訪問履歴の完全性・正確性を保証するものではありません。

## Cloudflare Workers

- Build command: `npm run build`
- Build output directory: `dist`

サイトの配信にはバックエンドや環境変数は不要です。データ更新用のGitHub Actionsでは `OPENAI_API_KEY` を使用します。

## 公式資料とOpenAIによる週次更新

`python3 scripts/update-ntv.py` で予告・OAまとめ・番組表を静的に取得し、放送日ごとにOpenAIへ送ります。
企画の統合、出演者、訪問国、総集編の除外はAIに任せます。片方の資料しかない日も処理します。
OAまとめは記事の日付、予告はタイトルから取得した放送日を使います。

追加分も `src/data/episodes.json` に保存します。Wikipedia由来の元の1,376件は内容と順序を保持します。
同じ資料は再照会せず、資料が変わった日だけ再処理し、その日全体の追加記録を置き換えます。
API失敗時は既存の記録を保持し、次回に再試行します。
日曜23時JSTのGitHub Actionsで検証後にmainへ自動コミット・pushします。
設定と実行方法は [運用手順](data/ntv/README.md) を参照してください。
