import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import { resolvePlaceLabel } from "./location";
import { COLOR_LABEL } from "./stationColor";
import JourneyForm from "./components/JourneyForm";
import MapView from "./components/MapView";
import RecommendationList from "./components/RecommendationList";
import StationDetails, { type ForecastState } from "./components/StationDetails";
import StatusBar from "./components/StatusBar";
import type {
  CandidateExclusion,
  GeoPoint,
  JourneyRecommendation,
  ModelStatus,
  PickTarget,
  RecommendationItem,
  RouteResult,
  StationSearchResult,
  Station,
  StationColor,
  StationForecast,
  StationStatus,
  Vehicle,
} from "./types";

const DEFAULT_ORIGIN: GeoPoint = { lat: 10.7075, lon: 106.705, label: "Nguyễn Hữu Thọ, Quận 7" };
const DEFAULT_DESTINATION: GeoPoint = { lat: 10.806, lon: 106.687, label: "Phú Nhuận" };

const CURRENT_VEHICLE_ID = "EV_VF5_PLUS";

/** How often station status and colours are re-read; the backend itself updates every 5 min. */
const STATUS_POLL_INTERVAL_MS = 30_000;

// Stable empty lists: a fresh `[]` per render would defeat memoization downstream (hover re-renders App).
const EMPTY_ITEMS: RecommendationItem[] = [];
const EMPTY_EXCLUSIONS: CandidateExclusion[] = [];

/**
 * Identity of a search: results are only valid for the inputs that produced them. Changing the
 * mode, an endpoint, the vehicle or the battery level makes earlier results stale.
 */
function searchKey(
  mode: "stations" | "route",
  origin: GeoPoint,
  destination: GeoPoint,
  vehicleId: string,
  soc: number,
): string {
  const end = mode === "route" ? `${destination.lat},${destination.lon}` : "";
  return [mode, `${origin.lat},${origin.lon}`, end, vehicleId, Math.round(soc * 100)].join("|");
}

async function settle<T>(call: () => Promise<T>): Promise<T | null> {
  try {
    return (await call()) ?? null;
  } catch {
    return null;
  }
}

export default function App() {
  const [currentTime, setCurrentTime] = useState(() => new Date());
  const [stations, setStations] = useState<Station[]>([]);
  const [statuses, setStatuses] = useState<Record<string, StationStatus>>({});
  // Marker colour is computed by the backend (availability thresholds live in its app_config).
  const [colors, setColors] = useState<Record<string, StationColor>>({});
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [vehicleId, setVehicleId] = useState("");
  const [initialSoc, setInitialSoc] = useState(0.5);
  const [searchMode, setSearchMode] = useState<"stations" | "route">("route");
  const [origin, setOrigin] = useState<GeoPoint>(DEFAULT_ORIGIN);
  const [destination, setDestination] = useState<GeoPoint>(DEFAULT_DESTINATION);
  const [originValid, setOriginValid] = useState(true);
  const [destinationValid, setDestinationValid] = useState(true);
  const [recommendation, setRecommendation] = useState<JourneyRecommendation | null>(null);
  const [stationSearch, setStationSearch] = useState<StationSearchResult | null>(null);
  // Key of the inputs behind `recommendation` / `stationSearch`; see searchKey().
  const [searchedKey, setSearchedKey] = useState<string | null>(null);
  // Inputs for which the driver asked to also see optional charging stops (battery is enough).
  const [stopsRequestedKey, setStopsRequestedKey] = useState<string | null>(null);
  const [route, setRoute] = useState<RouteResult | null>(null);
  const [journeyMarkersVisible, setJourneyMarkersVisible] = useState(true);
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [forecastResult, setForecastResult] = useState<
    { stationId: string; data: StationForecast | null } | null
  >(null);
  const [mapProvider, setMapProvider] = useState<"goong" | "osm">("goong");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(true);
  const [hoveredStationId, setHoveredStationId] = useState<string | null>(null);
  const [pickTarget, setPickTarget] = useState<PickTarget | null>(null);
  const [sortBy, setSortBy] = useState<"fastest" | "nearest" | "available">("fastest");
  const [debugMode] = useState(() => new URLSearchParams(window.location.search).get("debug") === "1");

  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const selectedVehicle = vehicles.find((item) => item.vehicle_id === vehicleId) ?? vehicles[0] ?? null;
  // "Tìm trạm" has a single start point; "Tìm đường" needs both ends.
  const locationsValid = originValid && (searchMode === "stations" || destinationValid);
  const currentKey = searchKey(searchMode, origin, destination, vehicleId, initialSoc);
  const currentKeyRef = useRef(currentKey);
  useEffect(() => {
    currentKeyRef.current = currentKey;
  }, [currentKey]);
  // Only results of the current mode *and* current inputs may drive the UI.
  const resultsFresh = searchedKey === currentKey;
  const freshRecommendation = resultsFresh && searchMode === "route" ? recommendation : null;
  const freshStationSearch = resultsFresh && searchMode === "stations" ? stationSearch : null;
  const stopsRequested = resultsFresh && stopsRequestedKey === currentKey;
  const isEnough = freshRecommendation?.case === "enough";
  // Only the "enough" case offers a voluntary stop, and only until it has been asked for.
  const canRequestOptionalStops = isEnough && !stopsRequested;

  // Calls overlap (poll, search, page load): only the most recently started one may write state,
  // so a slow older response can never overwrite newer data.
  const refreshSeq = useRef(0);
  const refreshStatuses = useCallback(async (stationList: Station[]) => {
    const seq = ++refreshSeq.current;
    const [records, stationColors] = await Promise.all([
      Promise.all(stationList.map((station) => api.stationStatus(station.properties.station_id))),
      api.stationColors(),
    ]);
    if (seq !== refreshSeq.current) return;
    setStatuses(Object.fromEntries(records.map((status) => [status.station_id, status])));
    setColors(stationColors);
  }, []);

  const loadInitialData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [stationList, vehicleList, model] = await Promise.all([
        api.stations(),
        api.vehicles(),
        api.modelStatus(),
      ]);
      if (!vehicleList.length) throw new Error("Backend không có hồ sơ xe.");
      const currentVehicle = vehicleList.find((item) => item.vehicle_id === CURRENT_VEHICLE_ID);
      if (!currentVehicle) throw new Error("Backend does not have the VinFast VF 5 Plus profile.");
      setStations(stationList);
      setVehicles([currentVehicle]);
      setModelStatus(model);
      setVehicleId(CURRENT_VEHICLE_ID);
      await refreshStatuses(stationList);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể tải dữ liệu backend.");
    } finally {
      setLoading(false);
    }
  }, [refreshStatuses]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadInitialData(), 0);
    return () => window.clearTimeout(timer);
  }, [loadInitialData]);

  // The backend moves port state every 5 min, so a page left open would otherwise show the
  // snapshot taken at load. Polling is quiet: a failed poll keeps the last data, it never raises
  // the error screen, and it pauses while the tab is hidden (catching up when it is shown again).
  useEffect(() => {
    if (stations.length === 0) return;
    let inFlight = false;
    const poll = () => {
      if (document.hidden || inFlight) return;
      inFlight = true;
      void settle(() => refreshStatuses(stations)).finally(() => {
        inFlight = false;
      });
    };
    const timer = window.setInterval(poll, STATUS_POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", poll);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [stations, refreshStatuses]);

  useEffect(() => {
    if (!selectedStationId) return;
    let cancelled = false;
    // Status is re-read together with the forecast: the backend simulation moves port state
    // every 5 min, so the snapshot taken at page load would disagree with the chart's "now" bar.
    void Promise.all([
      settle(() => api.stationStatus(selectedStationId)),
      settle(() => api.stationForecast(selectedStationId)),
      settle(() => api.stationColors()),
    ]).then(([freshStatus, data, freshColors]) => {
      if (cancelled) return;
      if (freshStatus) {
        setStatuses((current) => ({ ...current, [freshStatus.station_id]: freshStatus }));
      }
      if (freshColors) setColors((current) => ({ ...current, ...freshColors }));
      setForecastResult({ stationId: selectedStationId, data });
    });
    return () => {
      cancelled = true;
    };
  }, [selectedStationId]);

  const clearJourneyOverlay = useCallback(() => {
    setJourneyMarkersVisible(false);
    setRoute(null);
    setSelectedStationId(null);
    setHoveredStationId(null);
  }, []);

  const handleOriginChange = useCallback((point: GeoPoint) => {
    setOrigin(point);
    clearJourneyOverlay();
  }, [clearJourneyOverlay]);

  const handleDestinationChange = useCallback((point: GeoPoint) => {
    setDestination(point);
    clearJourneyOverlay();
  }, [clearJourneyOverlay]);

  const handleInitialSocChange = useCallback((soc: number) => {
    setInitialSoc(soc);
    setRoute(null);
  }, []);

  const handlePickTargetChange = useCallback((target: PickTarget | null) => {
    setPickTarget(target);
    if (target) clearJourneyOverlay();
  }, [clearJourneyOverlay]);

  const selectRecommendation = useCallback((item: RecommendationItem) => {
    setSelectedStationId(item.station_id);
    setRoute(item.route);
    setJourneyMarkersVisible(true);
  }, []);

  const submitJourney = async (includeOptionalStops = false) => {
    if (!vehicleId || !locationsValid) return;
    const key = currentKey;
    setSubmitting(true);
    setError(null);
    try {
      if (searchMode === "stations") {
        const result = await api.searchStations({
          location: origin,
          vehicle_id: vehicleId,
          battery_pct: Math.round(initialSoc * 100),
        });
        // The user may have edited the form while this was in flight: drop the stale answer.
        if (currentKeyRef.current !== key) return;
        // Same as the route search: the list below reads port counts from `statuses`.
        if (currentKeyRef.current !== key) return;
        // Same as the route search: the list below reads port counts from `statuses`.
        await refreshStatuses(stations);
        if (currentKeyRef.current !== key) return;
        setStationSearch(result);
        setSearchedKey(key);
        setSelectedStationId(result.stations[0]?.station_id ?? null);
        setRoute(result.stations[0]?.route ?? null);
        setJourneyMarkersVisible(true);
        return;
      }
      const result = await api.searchRoute({
        origin,
        destination,
        vehicle_id: vehicleId,
        battery_pct: Math.round(initialSoc * 100),
        include_optional_stops: includeOptionalStops || undefined,
      });
      if (currentKeyRef.current !== key) return;
      setRecommendation(result);
      setSearchedKey(key);
      setStopsRequestedKey(includeOptionalStops ? key : null);
      await refreshStatuses(stations);
      // "enough": every station is an optional detour, so don't pick one for the driver.
      if (result.case !== "enough" && result.recommendations.length) {
        selectRecommendation(result.recommendations[0]);
      } else {
        setSelectedStationId(null);
        setRoute(result.case === "enough" ? result.direct_route : null);
        setJourneyMarkersVisible(true);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể tìm trạm sạc.");
    } finally {
      setSubmitting(false);
    }
  };

  const selectedStation = useMemo(
    () => stations.find((item) => item.properties.station_id === selectedStationId) ?? null,
    [selectedStationId, stations],
  );
  // The forecast belongs to a station id; a stale one from a previous selection counts as loading.
  const currentForecast = forecastResult?.stationId === selectedStationId ? forecastResult : null;
  const forecastState: ForecastState = !selectedStationId
    ? "idle"
    : !currentForecast ? "loading" : currentForecast.data ? "ready" : "error";
  const activeItems = searchMode === "stations"
    ? freshStationSearch?.stations ?? EMPTY_ITEMS
    : freshRecommendation?.recommendations ?? EMPTY_ITEMS;
  const activeExclusions = searchMode === "stations"
    ? freshStationSearch?.excluded_candidates ?? EMPTY_EXCLUSIONS
    : freshRecommendation?.excluded_candidates ?? EMPTY_EXCLUSIONS;
  const searchRan = searchMode === "stations" ? freshStationSearch !== null : freshRecommendation !== null;
  // Arrival/wait/charge times exist only for stations the current search actually recommended.
  const selectedRecommendation =
    activeItems.find((item) => item.station_id === selectedStationId) ?? null;
  const orderedItems = useMemo(() => [...activeItems].sort((a, b) => {
    if (sortBy === "nearest") return a.distance_km - b.distance_km;
    if (sortBy === "available") return (statuses[b.station_id]?.available_ports ?? 0) - (statuses[a.station_id]?.available_ports ?? 0);
    return a.total_min - b.total_min;
  }), [activeItems, sortBy, statuses]);
  const notice = useMemo(() => {
    if (!freshRecommendation) return null;
    if (freshRecommendation.case === "enough") {
      // Shown inside the "go straight" card; the title/minutes come from the card itself.
      if (!stopsRequested) return "Bạn có thể ghé một trạm sạc dọc đường.";
      return freshRecommendation.recommendations.length > 0
        ? "Hoặc chọn một trạm bên dưới để ghé dọc đường."
        : "Không có trạm phù hợp để ghé dọc đường.";
    }
    if (freshRecommendation.case === "fallback") {
      const distance =
        freshRecommendation.missing_km != null
          ? ` (cách ${Math.round(freshRecommendation.missing_km)}km)`
          : "";
      const nearest = freshRecommendation.nearest_station_name
        ? ` Trạm gần nhất: ${freshRecommendation.nearest_station_name}${distance}.`
        : "";
      return `Pin không đủ tới trạm nào.${nearest}`;
    }
    return null;
  }, [freshRecommendation, stopsRequested]);
  const stationNotice = useMemo(() => {
    if (
      !freshStationSearch
      || freshStationSearch.stations.length > 0
      || freshStationSearch.missing_km == null
      || freshStationSearch.missing_km <= 0
    ) return null;
    const missing = Math.max(1, Math.ceil(freshStationSearch.missing_km));
    const nearest = freshStationSearch.nearest_station_name
      ? ` Trạm gần nhất: ${freshStationSearch.nearest_station_name} (cách ${missing}km).`
      : "";
    return `Pin không đủ tới trạm nào.${nearest}`;
  }, [freshStationSearch]);
  // "Enough" case: going straight is the original recommendation and stays selectable.
  const selectDirectRoute = useCallback(() => {
    setSelectedStationId(null);
    setHoveredStationId(null);
    if (freshRecommendation?.case === "enough") {
      setRoute(freshRecommendation.direct_route);
      setJourneyMarkersVisible(true);
    }
  }, [freshRecommendation]);
  const handleStationSelect = useCallback((stationId: string) => {
    setSelectedStationId(stationId);
    const item = activeItems.find((candidate) => candidate.station_id === stationId);
    if (item) {
      setRoute(item.route);
      setJourneyMarkersVisible(true);
    } else {
      // Not recommended: don't leave the previous station's route drawn as if it led here.
      setRoute(freshRecommendation?.direct_route ?? null);
    }
  }, [activeItems, freshRecommendation]);
  const handleProviderChange = useCallback(
    (provider: "goong" | "osm") => setMapProvider(provider),
    [],
  );
  const handleSearchModeChange = useCallback((mode: "stations" | "route") => {
    setPickTarget(null);
    clearJourneyOverlay();
    setSearchMode(mode);
  }, [clearJourneyOverlay]);
  const handleMapPick = useCallback(
    ({ lat, lon }: { lat: number; lon: number }) => {
      if (!pickTarget) return;
      const setPoint = pickTarget === "origin" ? setOrigin : setDestination;
      const setValid = pickTarget === "origin" ? setOriginValid : setDestinationValid;
      clearJourneyOverlay();
      setPoint({ lat, lon, label: null });
      setValid(true);
      setJourneyMarkersVisible(true);
      setPickTarget(null);
      // Show the marker immediately, then swap in the address if it arrives for this same point.
      void resolvePlaceLabel(lat, lon, "").then((label) => {
        if (!label) return;
        setPoint((current) => (current.lat === lat && current.lon === lon ? { ...current, label } : current));
      });
    },
    [clearJourneyOverlay, pickTarget],
  );
  useEffect(() => {
    if (!pickTarget) return;
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPickTarget(null);
    };
    window.addEventListener("keydown", cancelOnEscape);
    return () => window.removeEventListener("keydown", cancelOnEscape);
  }, [pickTarget]);
  const handleOriginValidityChange = useCallback((valid: boolean) => setOriginValid(valid), []);
  const handleDestinationValidityChange = useCallback(
    (valid: boolean) => setDestinationValid(valid),
    [],
  );

  if (loading) {
    return <main className="app-loading"><div className="loader" /><p>Đang kết nối Smart EV backend…</p></main>;
  }

  if (!vehicles.length) {
    return (
      <main className="app-loading error-screen">
        <h1>Không thể khởi tạo ứng dụng</h1>
        <p>{error ?? "Không có hồ sơ xe khả dụng."}</p>
        <button className="primary-button" onClick={() => void loadInitialData()}>Thử lại</button>
      </main>
    );
  }

  return (
    <main className="app-shell">
      {debugMode && (
        <header className="topbar">
          <StatusBar model={modelStatus} mapProvider={mapProvider} />
        </header>
      )}

      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(null)}>Đóng</button></div>}
      {debugMode && modelStatus && !modelStatus.release_ready && (
        <div className="fallback-banner" role="status">
          Occupancy model chưa sẵn sàng — backend đang dùng {modelStatus.prediction_source === "default" ? "giá trị mặc định cố định" : "persistence fallback"}.
        </div>
      )}

      <div className="workspace" id="top">
        <section className="control-column">
          {formOpen && (
            <JourneyForm
              searchMode={searchMode}
              vehicles={vehicles}
              vehicleId={vehicleId}
              initialSoc={initialSoc}
              origin={origin}
              destination={destination}
              locationsValid={locationsValid}
              pickTarget={pickTarget}
              onPickTargetChange={handlePickTargetChange}
              submitting={submitting}
              onSearchModeChange={handleSearchModeChange}
              onInitialSocChange={handleInitialSocChange}
              onOriginChange={handleOriginChange}
              onDestinationChange={handleDestinationChange}
              onOriginValidityChange={handleOriginValidityChange}
              onDestinationValidityChange={handleDestinationValidityChange}
              onSubmit={() => void submitJourney()}
            />
          )}
          {!formOpen && (
            <div className="collapsed-search-heading">
              <span className="step-label">01 · Tìm kiếm</span>
              <h1>{searchMode === "stations" ? "Tìm trạm trong tầm pin" : "Tìm trạm trên hành trình"}</h1>
            </div>
          )}
          <button
            className="panel-toggle"
            type="button"
            aria-label={formOpen ? "Ẩn biểu mẫu tìm kiếm" : "Hiện biểu mẫu tìm kiếm"}
            aria-expanded={formOpen}
            onClick={() => setFormOpen((open) => !open)}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
              <path d={formOpen ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"} />
            </svg>
          </button>
          <RecommendationList
            items={activeItems}
            exclusions={activeExclusions}
            stations={stations}
            selectedStationId={selectedStationId}
            hasRun={searchRan}
            notice={searchMode === "route" ? notice : stationNotice}
            title={searchMode === "stations" ? "Trạm gần điểm đến" : "Trạm trên hành trình"}
            directSelected={isEnough && selectedStationId === null}
            directMinutes={isEnough ? freshRecommendation.direct_min : undefined}
            onSelectDirect={searchMode === "route" && isEnough ? selectDirectRoute : undefined}
            onRequestOptionalStops={
              searchMode === "route" && canRequestOptionalStops
                ? () => void submitJourney(true)
                : undefined
            }
            optionalStopsLoading={submitting}
            emptyMessage={searchMode === "stations"
              ? `Không có trạm phù hợp trong phạm vi pin còn lại${freshStationSearch?.nearest_station_name ? `. Trạm gần nhất trong dữ liệu: ${freshStationSearch.nearest_station_name}` : ""}.`
              : "Không có trạm tương thích và tới được cho hành trình này."}
            onSelect={selectRecommendation}
            statuses={statuses}
            hoveredStationId={hoveredStationId}
            onHover={setHoveredStationId}
            onSortChange={setSortBy}
          />
        </section>

        <section className="map-column">
          <div className="map-frame">
            <MapView
              stations={stations}
              colors={colors}
              route={route}
              selectedStationId={selectedStationId}
              hoveredStationId={hoveredStationId}
              items={orderedItems}
              origin={journeyMarkersVisible ? origin : undefined}
              destination={journeyMarkersVisible && searchMode === "route" ? destination : undefined}
              pickTarget={pickTarget}
              onMapPick={handleMapPick}
              onStationSelect={handleStationSelect}
              onStationHover={setHoveredStationId}
              onProviderChange={handleProviderChange}
            />
            <div className="map-status-overlay">
              <div className="current-datetime" aria-label="Ngày giờ hiện tại">
                <span className="current-datetime-date">
                  {currentTime.toLocaleDateString("vi-VN", {
                    timeZone: "Asia/Ho_Chi_Minh",
                    weekday: "long",
                    day: "2-digit",
                    month: "2-digit",
                    year: "numeric",
                  })}
                </span>
                <time className="current-datetime-time" dateTime={currentTime.toISOString()}>
                  {currentTime.toLocaleTimeString("vi-VN", {
                    timeZone: "Asia/Ho_Chi_Minh",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: false,
                  })}
                </time>
              </div>
              <div className="map-legend map-legend-overlay">
                {(["green", "yellow", "red", "grey"] as const).map((color) => (
                  <span key={color}><i className={`legend-dot ${color}`} />{COLOR_LABEL[color]}</span>
                ))}
              </div>
            </div>
            {pickTarget && (
              <div className="map-pick-hint" role="status">
                <span>
                  Nhấp vào bản đồ để chọn{" "}
                  {pickTarget === "destination" ? "điểm đến" : searchMode === "stations" ? "điểm bắt đầu" : "điểm đi"}
                  {" "}· Esc để huỷ
                </span>
                <button type="button" onClick={() => setPickTarget(null)}>Huỷ</button>
              </div>
            )}
            {debugMode && <span className="map-provider-chip">{mapProvider === "goong" ? "Goong Maps" : "Leaflet · OSM fallback"}</span>}
            <StationDetails
              station={selectedStation}
              status={selectedStationId ? statuses[selectedStationId] ?? null : null}
              color={selectedStationId ? colors[selectedStationId] ?? null : null}
              recommendation={selectedRecommendation}
              searchRan={searchRan}
              exclusionReasons={
                activeExclusions.find((item) => item.station_id === selectedStationId)?.reason_codes
              }
              forecast={currentForecast?.data ?? null}
              forecastState={forecastState}
              onClose={() => {
                if (isEnough) selectDirectRoute();
                else setSelectedStationId(null);
              }}
            />
          </div>
        </section>
      </div>
    </main>
  );
}
