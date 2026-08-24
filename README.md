# イッテQ 世界地図

「世界の果てまでイッテQ!」で訪れたことのある国を、世界地図上で色付き表示する静的Webサイトです。

現在はMVPとして、Wikipediaの放送リストから取得した訪問国を表示しています。データは確認できた範囲で段階的に補正・追加する方針です。

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
python3 scripts/collect-data.py
```

取得元の記載内容や表記揺れを含むため、実際の訪問履歴の完全性・正確性を保証するものではありません。

## Cloudflare Pages

- Build command: `npm run build`
- Build output directory: `dist`

バックエンドや環境変数は不要です。
