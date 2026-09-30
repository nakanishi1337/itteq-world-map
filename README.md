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

現在の更新は、下記の公式資料による週次更新を使います。`scripts/collect-data.py` は旧Wikipediaデータの取得用で、現在の記事からの再取得は保証しません。

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

放送日・企画名・出演者・本文・出典URLを抽出します。記事単位の解析問題は
`articleIssues`、日付・企画名・出演者の欠落は `reviewReasons` に残します。
国の判定と訪問データへの反映は、下記の週次更新が担当します。

## 公式資料とOpenAIによる週次更新

`python3 scripts/update-ntv.py` で予告を静的に取得します。
企画見出しの地名で国を取得できない場合は、予告本文・同日の番組表・OAまとめを
OpenAI APIへ送り、国コードのJSONを取得します。都市・地域表記にも対応します。
予告がない企画はOAまとめのタイトル・本文から、国ごとの出演者と訪問国をAIで取得します。
予告との対応付けもAIで確認し、重複する企画は追加しません。

追加分も `src/data/episodes.json` に追記し、アプリと週次更新が同じファイルを使います。
Wikipedia由来の元の1,376件は内容と順序を保持します。
処理済みの資料は再照会せず、変更時には企画の国リストを置き換えます。
API失敗時は既存の記録を保持し、次回に再試行します。
日曜23時JSTのGitHub Actionsで検証後にmainへ自動コミット・pushします。
設定・資料の対応付け・手動訂正は [運用手順](data/ntv/README.md) を参照してください。
