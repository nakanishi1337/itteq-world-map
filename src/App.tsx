import { useMemo, useState } from "react";
import WorldMapView, { type VisitedCountry } from "./components/WorldMapView";
import episodesData from "./data/episodes.json";

type Episode = { date: string | null; countryCode: string; countryName: string; project: string; performers: string[]; source: string };
const episodes = episodesData as Episode[];

function aggregateCountries(items: Episode[]): VisitedCountry[] {
  const countries = new Map<string, VisitedCountry>();
  items.forEach((episode) => {
    const current = countries.get(episode.countryCode);
    countries.set(episode.countryCode, { countryCode: episode.countryCode, countryName: episode.countryName, visits: (current?.visits ?? 0) + 1 });
  });
  return [...countries.values()];
}

export default function App() {
  const [selectedPerformer, setSelectedPerformer] = useState("");
  const [showUnvisited, setShowUnvisited] = useState(false);
  const [selectedCountry, setSelectedCountry] = useState<VisitedCountry | null>(null);
  const performers = useMemo(() => {
    const appearanceCounts = new Map<string, number>();
    episodes.forEach((episode) => episode.performers.forEach((performer) => {
      appearanceCounts.set(performer, (appearanceCounts.get(performer) ?? 0) + 1);
    }));
    return [...appearanceCounts.keys()].sort((a, b) =>
      (appearanceCounts.get(b) ?? 0) - (appearanceCounts.get(a) ?? 0) || a.localeCompare(b, "ja"),
    );
  }, []);
  const filteredEpisodes = useMemo(
    () => selectedPerformer ? episodes.filter((episode) => episode.performers.includes(selectedPerformer)) : episodes,
    [selectedPerformer],
  );
  const countries = useMemo(() => aggregateCountries(filteredEpisodes), [filteredEpisodes]);
  const selectedEpisodes = useMemo(
    () => selectedCountry ? filteredEpisodes.filter((episode) => episode.countryCode === selectedCountry.countryCode) : [],
    [filteredEpisodes, selectedCountry],
  );
  const formatDate = (date: string | null) => date
    ? new Intl.DateTimeFormat("ja-JP", { year: "numeric", month: "long", day: "numeric" }).format(new Date(`${date}T00:00:00+09:00`))
    : "放送日不明";
  return (
    <main>
      <header className="hero"><p className="eyebrow">世界の果てまで、ひと目で。</p><h1>イッテQ 世界地図</h1><p className="intro">「謎とき冒険バラエティー 世界の果てまでイッテQ!」で訪れた国を、世界地図で一覧できます。</p></header>
      <section className="map-card" aria-labelledby="map-title">
        <div className="map-heading">
          <div><p className="section-label">WORLD MAP</p><h2 id="map-title">これまでに訪れた国</h2></div>
          <div className="map-actions">
            <label className="unvisited-toggle">
              <input type="checkbox" checked={showUnvisited} onChange={(event) => setShowUnvisited(event.target.checked)} />
              未訪問国を表示
            </label>
            <label className="performer-filter">出演者で絞り込む
              <select value={selectedPerformer} onChange={(event) => { setSelectedPerformer(event.target.value); setSelectedCountry(null); }}>
                <option value="">すべての出演者</option>
                {performers.map((performer) => <option key={performer} value={performer}>{performer}</option>)}
              </select>
            </label>
            <div className="counter" aria-label={`訪問済み ${countries.length}か国`}><strong>{countries.length}</strong><span>か国</span></div>
          </div>
        </div>
        <WorldMapView countries={countries} showUnvisited={showUnvisited} onSelect={setSelectedCountry} />
        <div className="map-footer"><p className={`legend ${showUnvisited ? "is-unvisited" : ""}`}><span aria-hidden="true" />色付き：{showUnvisited ? "未訪問" : "訪問済み"}</p><p className="hint"><span className="desktop-hint">地図上の国をクリックすると、訪問状況を確認できます</span><span className="mobile-hint">地図上の国をタップすると、訪問状況を確認できます</span></p></div>
      </section>
      <aside className={`selection ${selectedCountry ? "is-visible" : ""}`} aria-live="polite">
        {selectedCountry ? <><p>選択した国</p><strong>{selectedCountry.countryName}</strong><span>{selectedCountry.visits > 0 ? `訪問件数 ${selectedCountry.visits}件` : selectedPerformer ? "該当する訪問記録なし" : "未訪問"}</span></> : <p>{selectedPerformer ? `${selectedPerformer}の訪問国を表示しています。地図から国を選んでください。` : "地図から国を選ぶと、ここに表示されます。"}</p>}
      </aside>
      {selectedCountry && (
        <section className="broadcasts" aria-labelledby="broadcasts-title">
          <div className="broadcasts-heading">
            <div><p className="section-label">BROADCAST LIST</p><h2 id="broadcasts-title">{selectedCountry.countryName}の放送リスト</h2></div>
            <span>{selectedEpisodes.length}件</span>
          </div>
          {selectedEpisodes.length > 0 ? (
            <ol className="broadcast-list">
              {selectedEpisodes.map((episode, index) => (
                <li key={`${episode.date}-${episode.project}-${index}`}>
                  <time dateTime={episode.date ?? undefined}>{formatDate(episode.date)}</time>
                  <div>
                    <strong>{episode.project}</strong>
                    {episode.performers.length > 0 && <p>出演：{episode.performers.join("、")}</p>}
                  </div>
                </li>
              ))}
            </ol>
          ) : <p className="no-broadcasts">この国の放送記録はありません。</p>}
        </section>
      )}
      <footer><p>2007年からの<a href="https://ja.wikipedia.org/wiki/世界の果てまでイッテQ!#放送リスト" target="_blank" rel="noreferrer">Wikipedia放送リスト</a>をもとに、訪問先を記録しています。</p><small>制作：<a href="https://github.com/nakanishi1337" target="_blank" rel="noreferrer">@nakanishi1337</a> ｜ 非公式の個人制作サイトです。掲載内容の完全性・正確性を保証するものではありません。</small></footer>
    </main>
  );
}
