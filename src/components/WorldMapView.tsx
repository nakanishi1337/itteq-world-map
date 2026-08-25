import { useMemo, useRef, useState, type PointerEvent, type TouchEvent } from "react";
import { geoMercator, geoPath } from "d3-geo";
import isoCountries from "i18n-iso-countries";
import jaLocale from "i18n-iso-countries/langs/ja.json";
import { feature } from "topojson-client";
import worldAtlas from "world-atlas/countries-50m.json";
import type { Feature, FeatureCollection, GeoJsonProperties, Geometry } from "geojson";
import type { Objects, Topology } from "topojson-specification";

export type VisitedCountry = { countryCode: string; countryName: string; visits: number };
type Props = { countries: VisitedCountry[]; showUnvisited: boolean; onSelect: (country: VisitedCountry) => void };

const WIDTH = 1200;
const MAP_HEIGHT = 590;
const HEIGHT = 680;
const ZOOM_LEVELS = [1, 2, 3, 4, 6, 8, 12, 16] as const;
const MAX_ZOOM = ZOOM_LEVELS.at(-1)!;
isoCountries.registerLocale(jaLocale);
type CountryProperties = GeoJsonProperties & { name?: string };
type CountryFeature = Feature<Geometry, CountryProperties> & { id?: string | number };
// Natural Earthの50mデータで唯一省略される国連加盟国。首都フナフティを代表点として補う。
const TUVALU_FEATURE: CountryFeature = {
  type: "Feature",
  id: "798",
  properties: { name: "Tuvalu" },
  geometry: { type: "Point", coordinates: [179.194, -8.521] },
};
const clampView = (zoom: number, x: number, y: number) => {
  const maxX = WIDTH * (zoom - 1) / 2;
  const maxY = HEIGHT * (zoom - 1) / 2;
  return {
    zoom,
    x: Math.min(maxX, Math.max(-maxX, x)),
    y: Math.min(maxY, Math.max(-maxY, y)),
  };
};

export default function WorldMapView({ countries, showUnvisited, onSelect }: Props) {
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const pinchStart = useRef<{ distance: number; zoom: number; x: number; y: number; centerX: number; centerY: number } | null>(null);
  const touchDragStart = useRef<{ clientX: number; clientY: number; x: number; y: number; moved: boolean } | null>(null);
  const dragStart = useRef<{ clientX: number; clientY: number; x: number; y: number; moved: boolean; pointerId: number } | null>(null);
  const suppressClick = useRef(false);
  const visitedByCode = useMemo(
    () => new Map(countries.map((country) => [country.countryCode.toUpperCase(), country])),
    [countries],
  );
  const map = useMemo(() => {
    const topology = worldAtlas as unknown as Topology<Objects<GeoJsonProperties>>;
    const collection = feature(topology, topology.objects.countries) as unknown as FeatureCollection<Geometry, CountryProperties>;
    collection.features.push(TUVALU_FEATURE);
    // 南極（ISO numeric: 010）を除いて可住地域へ表示領域を合わせる。
    const visibleCollection: FeatureCollection<Geometry, CountryProperties> = {
      ...collection,
      features: collection.features.filter((country) => String(country.id).padStart(3, "0") !== "010"),
    };
    // 日本を中央付近に置き、アフリカを分断しないよう大西洋上に継ぎ目を置く。
    const projection = geoMercator().rotate([-150, 0]).fitExtent([[8, 8], [WIDTH - 8, MAP_HEIGHT - 8]], visibleCollection);
    const [translateX, translateY] = projection.translate();
    projection.scale(projection.scale() * 1.06).translate([translateX, translateY + 20]);
    const path = geoPath(projection);
    // 投影倍率には含めないが、南極自体は画面下端に入る部分だけ描画する。
    return collection.features.map((country) => {
      const bounds = path.bounds(country);
      const width = bounds[1][0] - bounds[0][0];
      const height = bounds[1][1] - bounds[0][1];
      return { country: country as CountryFeature, path: path(country) ?? "", hasLargeHitArea: width < 12 || height < 12 };
    });
  }, []);

  const countryCode = (country: CountryFeature) => isoCountries.numericToAlpha2(String(country.id).padStart(3, "0"));
  const touchDistance = (event: TouchEvent<SVGSVGElement>) => {
    const [first, second] = [event.touches[0], event.touches[1]];
    return Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY);
  };
  const touchCenter = (event: TouchEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: ((event.touches[0].clientX + event.touches[1].clientX) / 2 - rect.left) * WIDTH / rect.width,
      y: ((event.touches[0].clientY + event.touches[1].clientY) / 2 - rect.top) * HEIGHT / rect.height,
    };
  };
  const handleTouchStart = (event: TouchEvent<SVGSVGElement>) => {
    if (event.touches.length === 2) {
      touchDragStart.current = null;
      const center = touchCenter(event);
      pinchStart.current = { distance: touchDistance(event), ...view, centerX: center.x, centerY: center.y };
    } else if (event.touches.length === 1 && view.zoom > 1) {
      const touch = event.touches[0];
      touchDragStart.current = { clientX: touch.clientX, clientY: touch.clientY, x: view.x, y: view.y, moved: false };
    }
  };
  const handleTouchMove = (event: TouchEvent<SVGSVGElement>) => {
    if (event.touches.length === 2 && pinchStart.current) {
      event.preventDefault();
      const start = pinchStart.current;
      const center = touchCenter(event);
      const nextZoom = Math.min(MAX_ZOOM, Math.max(1, start.zoom * touchDistance(event) / start.distance));
      const ratio = nextZoom / start.zoom;
      setView(clampView(
        nextZoom,
        start.x + (center.x - start.centerX) + (1 - ratio) * (start.centerX - WIDTH / 2 - start.x),
        start.y + (center.y - start.centerY) + (1 - ratio) * (start.centerY - HEIGHT / 2 - start.y),
      ));
      return;
    }
    if (event.touches.length !== 1 || !touchDragStart.current) return;
    const start = touchDragStart.current;
    const rect = event.currentTarget.getBoundingClientRect();
    const touch = event.touches[0];
    const dx = (touch.clientX - start.clientX) * WIDTH / rect.width;
    const dy = (touch.clientY - start.clientY) * HEIGHT / rect.height;
    if (!start.moved && Math.abs(dx) + Math.abs(dy) > 6) start.moved = true;
    if (!start.moved) return;
    event.preventDefault();
    setView((current) => clampView(current.zoom, start.x + dx, start.y + dy));
  };
  const handleTouchEnd = () => {
    if (touchDragStart.current?.moved) {
      suppressClick.current = true;
      requestAnimationFrame(() => { suppressClick.current = false; });
    }
    pinchStart.current = null;
    touchDragStart.current = null;
  };
  const zoomAt = (nextZoom: number, pointX = WIDTH / 2, pointY = HEIGHT / 2) => {
    setView((current) => {
      const zoom = Math.min(MAX_ZOOM, Math.max(1, nextZoom));
      if (zoom === 1) return { zoom: 1, x: 0, y: 0 };
      const ratio = zoom / current.zoom;
      return clampView(zoom, current.x + (1 - ratio) * (pointX - WIDTH / 2 - current.x), current.y + (1 - ratio) * (pointY - HEIGHT / 2 - current.y));
    });
  };
  const nextZoomLevel = () => ZOOM_LEVELS.find((zoom) => zoom > view.zoom) ?? MAX_ZOOM;
  const previousZoomLevel = () => [...ZOOM_LEVELS].reverse().find((zoom) => zoom < view.zoom) ?? 1;
  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.pointerType !== "mouse" || view.zoom === 1) return;
    dragStart.current = { clientX: event.clientX, clientY: event.clientY, x: view.x, y: view.y, moved: false, pointerId: event.pointerId };
  };
  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!dragStart.current || event.pointerType !== "mouse") return;
    const start = dragStart.current;
    const rect = event.currentTarget.getBoundingClientRect();
    const dx = (event.clientX - start.clientX) * WIDTH / rect.width;
    const dy = (event.clientY - start.clientY) * HEIGHT / rect.height;
    if (!start.moved && Math.abs(dx) + Math.abs(dy) > 6) {
      start.moved = true;
      event.currentTarget.setPointerCapture(start.pointerId);
    }
    if (!start.moved) return;
    setView((current) => clampView(current.zoom, start.x + dx, start.y + dy));
  };
  const handlePointerUp = () => {
    if (dragStart.current?.moved) {
      suppressClick.current = true;
      requestAnimationFrame(() => { suppressClick.current = false; });
    }
    dragStart.current = null;
  };

  return (
    <div className="world-map">
      <div className="map-zoom-controls" aria-label="地図の拡大縮小">
        <button type="button" onClick={() => zoomAt(nextZoomLevel())} disabled={view.zoom === MAX_ZOOM} aria-label="地図を拡大">＋</button>
        <button type="button" onClick={() => zoomAt(previousZoomLevel())} disabled={view.zoom === 1} aria-label="地図を縮小">−</button>
        <button type="button" className="map-zoom-reset" onClick={() => setView({ zoom: 1, x: 0, y: 0 })} disabled={view.zoom === 1} aria-label="地図を全体表示" title="地図を全体表示">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 8V3h5M12 3h5v5M17 12v5h-5M8 17H3v-5" /></svg>
        </button>
      </div>
      <svg className={view.zoom > 1 ? "is-zoomed" : ""} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="日本を中心にしたイッテQ世界地図" onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp} onTouchStart={handleTouchStart} onTouchMove={handleTouchMove} onTouchEnd={handleTouchEnd} onTouchCancel={handleTouchEnd}>
        <rect className="map-ocean" width={WIDTH} height={HEIGHT} rx="16" />
        <g transform={`translate(${view.x} ${view.y}) translate(${WIDTH / 2} ${HEIGHT / 2}) scale(${view.zoom}) translate(${-WIDTH / 2} ${-HEIGHT / 2})`} className="map-zoom-layer">
          {map.map(({ country, path, hasLargeHitArea }) => {
            const code = countryCode(country);
            const visited = code ? visitedByCode.get(code) : undefined;
            const name = visited?.countryName ?? (code ? isoCountries.getName(code, "ja") : undefined) ?? country.properties?.name ?? "国名不明";
            const selectedCountry: VisitedCountry = visited ?? { countryCode: code ?? String(country.id), countryName: name, visits: 0 };
            const selectCountry = () => { if (!suppressClick.current) onSelect(selectedCountry); };
            return (
              <g key={String(country.id)} className="map-country-shape">
                <path
                  d={path}
                  className={`map-country ${!showUnvisited && visited ? "is-visited" : ""} ${showUnvisited && !visited ? "is-unvisited-highlighted" : ""}`}
                  role="button" tabIndex={0}
                  aria-label={visited ? `${name}、訪問記録${visited.visits}件` : `${name}、未訪問`}
                  onClick={selectCountry}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault(); onSelect(selectedCountry);
                    }
                  }}
                ><title>{name}</title></path>
                {hasLargeHitArea && <path d={path} className="map-country-hit" aria-hidden="true" onClick={selectCountry} />}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
