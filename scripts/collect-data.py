#!/usr/bin/env python3
"""Wikipediaの放送リストから訪問国データを生成する。標準ライブラリのみ使用。"""

import argparse
import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ARTICLE = "世界の果てまでイッテQ!"
SOURCE_URL = "https://ja.wikipedia.org/wiki/世界の果てまでイッテQ!#放送リスト"
API_URL = "https://ja.wikipedia.org/w/api.php"

# 放送リストに現れる国・地域名。値は ISO 3166-1 alpha-2（XKのみ慣用コード）。
COUNTRY_CODES = {
    "アラブ首長国連邦": "AE", "南アフリカ共和国": "ZA", "トリニダード・トバゴ": "TT",
    "スヴァールバル諸島およびヤンマイエン島": "SJ", "ブルネイ・ダルサラーム国": "BN",
    "ドミニカ共和国": "DO", "パプアニューギニア": "PG", "フランス領ポリネシア": "PF",
    "中央アフリカ共和国": "CF", "ボスニア・ヘルツェゴビナ": "BA", "コートジボワール": "CI",
    "中華人民共和国": "CN", "フィリピン共和国": "PH", "マーシャル諸島": "MH",
    "ミクロネシア連邦": "FM", "ニュージーランド": "NZ", "ニューカレドニア": "NC",
    "北マケドニア": "MK", "サウジアラビア": "SA", "ブルキナファソ": "BF",
    "赤道ギニア": "GQ", "東ティモール": "TL", "チェコ共和国": "CZ",
    "オーストラリア": "AU", "オーストリア": "AT", "アメリカ合衆国": "US",
    "イギリス・スコットランド": "GB", "北アイルランド": "GB", "スコットランド": "GB",
    "グリーンランド": "GL", "シント・マールテン": "SX", "ケイマン諸島": "KY",
    "タイ王国": "TH", "大韓民国": "KR", "中華民国": "TW", "モンゴル国": "MN",
    "マリ共和国": "ML", "南アフリカ": "ZA", "韓国": "KR", "中国": "CN",
    "台湾": "TW", "ブルネイ": "BN", "フィリピン": "PH", "チェコ": "CZ",
    "アフガニスタン": "AF", "アルバニア": "AL", "アルジェリア": "DZ", "アンドラ": "AD",
    "アンゴラ": "AO", "アンティグア・バーブーダ": "AG", "アルゼンチン": "AR",
    "アルメニア": "AM", "アゼルバイジャン": "AZ", "バハマ": "BS", "バーレーン": "BH",
    "バングラデシュ": "BD", "バルバドス": "BB", "ベラルーシ": "BY", "ベルギー": "BE",
    "ベリーズ": "BZ", "ベナン": "BJ", "ブータン": "BT", "ボリビア": "BO",
    "ボツワナ": "BW", "ブラジル": "BR", "ブルガリア": "BG", "ブルンジ": "BI",
    "カンボジア": "KH", "カメルーン": "CM", "カナダ": "CA", "カーボベルデ": "CV",
    "チャド": "TD", "チリ": "CL", "コロンビア": "CO", "コモロ": "KM",
    "コンゴ共和国": "CG", "コンゴ民主共和国": "CD", "コスタリカ": "CR", "クロアチア": "HR",
    "キューバ": "CU", "キプロス": "CY", "デンマーク": "DK", "ジブチ": "DJ",
    "ドミニカ国": "DM", "エクアドル": "EC", "エジプト": "EG", "エルサルバドル": "SV",
    "エリトリア": "ER", "エストニア": "EE", "エスワティニ": "SZ", "エチオピア": "ET",
    "フィジー": "FJ", "フィンランド": "FI", "フランス": "FR", "ガボン": "GA",
    "ガンビア": "GM", "ジョージア": "GE", "ドイツ": "DE", "ガーナ": "GH",
    "ギリシャ": "GR", "グレナダ": "GD", "グアテマラ": "GT", "ギニア": "GN",
    "ギニアビサウ": "GW", "ガイアナ": "GY", "ハイチ": "HT", "ホンジュラス": "HN",
    "ハンガリー": "HU", "アイスランド": "IS", "インド": "IN", "インドネシア": "ID",
    "イラン": "IR", "イラク": "IQ", "アイルランド": "IE", "イスラエル": "IL",
    "イタリア": "IT", "ジャマイカ": "JM", "日本": "JP", "ヨルダン": "JO",
    "カザフスタン": "KZ", "ケニア": "KE", "キリバス": "KI", "コソボ": "XK",
    "クウェート": "KW", "キルギス": "KG", "ラオス": "LA", "ラトビア": "LV",
    "レバノン": "LB", "レソト": "LS", "リベリア": "LR", "リビア": "LY",
    "リヒテンシュタイン": "LI", "リトアニア": "LT", "ルクセンブルク": "LU",
    "マダガスカル": "MG", "マラウイ": "MW", "マレーシア": "MY", "モルディブ": "MV",
    "マルタ": "MT", "モーリタニア": "MR", "モーリシャス": "MU", "メキシコ": "MX",
    "モルドバ": "MD", "モナコ": "MC", "モンゴル": "MN", "モンテネグロ": "ME",
    "モロッコ": "MA", "モザンビーク": "MZ", "ミャンマー": "MM", "ナミビア": "NA",
    "ナウル": "NR", "ネパール": "NP", "オランダ": "NL", "ニカラグア": "NI",
    "ニジェール": "NE", "ナイジェリア": "NG", "北朝鮮": "KP", "ノルウェー": "NO",
    "オマーン": "OM", "パキスタン": "PK", "パラオ": "PW", "パレスチナ": "PS",
    "パナマ": "PA", "パラグアイ": "PY", "ペルー": "PE", "ポーランド": "PL",
    "ポルトガル": "PT", "カタール": "QA", "ルーマニア": "RO", "ロシア": "RU",
    "ルワンダ": "RW", "サモア": "WS", "サンマリノ": "SM", "セネガル": "SN",
    "セルビア": "RS", "セーシェル": "SC", "シエラレオネ": "SL", "シンガポール": "SG",
    "スロバキア": "SK", "スロベニア": "SI", "ソロモン諸島": "SB", "ソマリア": "SO",
    "南スーダン": "SS", "スペイン": "ES", "スリランカ": "LK", "スーダン": "SD",
    "スリナム": "SR", "スウェーデン": "SE", "スイス": "CH", "シリア": "SY",
    "タジキスタン": "TJ", "タンザニア": "TZ", "タイ": "TH", "トーゴ": "TG",
    "トンガ": "TO", "チュニジア": "TN", "トルコ": "TR", "トルクメニスタン": "TM",
    "ツバル": "TV", "ウガンダ": "UG", "ウクライナ": "UA", "ウルグアイ": "UY",
    "ウズベキスタン": "UZ", "バヌアツ": "VU", "バチカン": "VA", "ベネズエラ": "VE",
    "ベトナム": "VN", "イエメン": "YE", "ザンビア": "ZM", "ジンバブエ": "ZW",
    "プエルトリコ": "PR", "香港": "HK", "マカオ": "MO", "サイパン島": "MP",
    "アラスカ": "US", "ハワイ": "US", "ドバイ": "AE", "南極": "AQ",
}


def fetch_wikitext() -> str:
    params = urllib.parse.urlencode({"action": "parse", "page": ARTICLE, "section": "8", "prop": "wikitext", "format": "json", "utf8": "1"})
    request = urllib.request.Request(f"{API_URL}?{params}", headers={"User-Agent": "itteq-world-map/0.1 (personal research project)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["parse"]["wikitext"]["*"]


def clean_markup(value: str) -> str:
    value = re.sub(r"<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/>", "", value, flags=re.S)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"'{2,}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(re.sub(r"[ \t]+", " ", value)).strip()


def parse_cells(row: str) -> list[str]:
    cells: list[str] = []
    for line in row.splitlines():
        if not line or line.startswith(("{|", "|}")):
            continue
        if line[0] in "!|" and not line.startswith("|-"):
            content = line[1:]
            if "|" in content and re.match(r"\s*(?:rowspan|colspan|style|class)=", content):
                content = content.split("|", 1)[1]
            cells.append(content.strip())
        elif cells:
            cells[-1] += "\n" + line.strip()
    return [clean_markup(cell) for cell in cells]


def countries_in(value: str) -> list[tuple[str, str]]:
    found: list[tuple[int, int, str, str]] = []
    for name, code in COUNTRY_CODES.items():
        for match in re.finditer(re.escape(name), value):
            found.append((match.start(), -len(name), code, name))
    result: list[tuple[str, str]] = []
    used_positions: list[tuple[int, int]] = []
    seen_codes: set[str] = set()
    for start, negative_length, code, name in sorted(found):
        end = start - negative_length
        if any(start >= used_start and end <= used_end for used_start, used_end in used_positions):
            continue
        used_positions.append((start, end))
        if code not in seen_codes:
            result.append((code, canonical_name(code, name)))
            seen_codes.add(code)
    return result


def canonical_name(code: str, fallback: str) -> str:
    preferred = {"US": "アメリカ", "GB": "イギリス", "CN": "中国", "KR": "韓国", "TW": "台湾", "AE": "アラブ首長国連邦", "ZA": "南アフリカ", "MN": "モンゴル", "TH": "タイ"}
    return preferred.get(code, fallback)


def parse_date(year: int, value: str) -> str | None:
    match = re.search(r"(\d{1,2})月(\d{1,2})日", value)
    if not match:
        return None
    try:
        return dt.date(year, int(match.group(1)), int(match.group(2))).isoformat()
    except ValueError:
        return None


def split_performers(value: str) -> list[str]:
    value = re.sub(r"（[^）]*）", "", value)
    return [part.strip() for part in re.split(r"[、\n]", value) if part.strip()]


def collect(wikitext: str) -> list[dict]:
    episodes: list[dict] = []
    year = 2007
    last_date: str | None = None
    last_month: int | None = None
    # 年ごとのtable境界も行境界として扱う（直前の最終行との結合を防ぐ）。
    wikitext = re.sub(r"^\|}\s*\n\{\|[^\n]*$", "|-", wikitext, flags=re.M)
    for row in re.split(r"^\|-\s*$", wikitext, flags=re.M):
        cells = parse_cells(row)
        if not cells:
            continue
        year_match = next((re.fullmatch(r"(20\d{2})年?", cell) for cell in cells if re.fullmatch(r"(20\d{2})年?", cell)), None)
        if year_match:
            heading_year = int(year_match.group(1))
            # 元表には2023年の見出しが「2022」となっているため、年末後の重複見出しを補正。
            year = year + 1 if heading_year <= year and last_month is not None and last_month >= 10 else heading_year
            last_date = None
            last_month = None
            continue
        date_index = next((i for i, cell in enumerate(cells[:3]) if re.search(r"\d{1,2}月\d{1,2}日", cell)), None)
        if date_index is not None:
            month_match = re.search(r"(\d{1,2})月", cells[date_index])
            month = int(month_match.group(1)) if month_match else None
            # 2023年のように年見出しが欠けた編集にも、12月→1月の推移で対応する。
            if month is not None and last_month is not None and last_month >= 10 and month <= 3:
                year += 1
            last_date = parse_date(year, cells[date_index])
            last_month = month
            country_index = date_index + 1
        else:
            country_index = 0
        if country_index >= len(cells):
            continue
        destinations = countries_in(cells[country_index])
        if not destinations:
            continue
        project = cells[country_index + 1] if country_index + 1 < len(cells) else ""
        project_lines = [line.strip() for line in project.splitlines() if line.strip()]
        performers = split_performers(cells[-1]) if len(cells) >= country_index + 3 else []
        for index, (code, name) in enumerate(destinations):
            country_project = project_lines[index] if len(project_lines) == len(destinations) else project
            episodes.append({"date": last_date, "countryCode": code, "countryName": name, "project": country_project, "performers": performers, "source": SOURCE_URL})
    return episodes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "src/data/episodes.json")
    args = parser.parse_args()
    episodes = collect(fetch_wikitext())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(episodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(episodes)} records / {len({item['countryCode'] for item in episodes})} countries -> {args.output}")


if __name__ == "__main__":
    main()
