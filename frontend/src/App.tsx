import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import JourneyForm from "./components/JourneyForm";
import MapView from "./components/MapView";
import RecommendationList from "./components/RecommendationList";
import StationDetails from "./components/StationDetails";
import StatusBar from "./components/StatusBar";
import type {
  GeoPoint,
  JourneyRecommendation,
  ModelStatus,
  RecommendationItem,
  RouteResult,
  Station,
  StationStatus,
  Vehicle,
} from "./types";

const DEFAULT_ORIGIN: GeoPoint = { lat: 10.7075, lon: 106.705, label: "Nguyễn Hữu Thọ, Quận 7" };
const DEFAULT_DESTINATION: GeoPoint = { lat: 10.806, lon: 106.687, label: "Phú Nhuận" };

export default function App() {
  const [stations, setStations] = useState<Station[]>([]);
  const [statuses, setStatuses] = useState<Record<string, StationStatus>>({});
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [vehicleId, setVehicleId] = useState("");
  const [initialSoc, setInitialSoc] = useState(0.5);
  const [origin, setOrigin] = useState<GeoPoint>(DEFAULT_ORIGIN);
  const [destination, setDestination] = useState<GeoPoint>(DEFAULT_DESTINATION);
  const [originValid, setOriginValid] = useState(true);
  const [destinationValid, setDestinationValid] = useState(true);
  const [recommendation, setRecommendation] = useState<JourneyRecommendation | null>(null);
  const [route, setRoute] = useState<RouteResult | null>(null);
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [mapProvider, setMapProvider] = useState<"goong" | "osm">("goong");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedVehicle = vehicles.find((item) => item.vehicle_id === vehicleId) ?? vehicles[0] ?? null;

  const refreshStatuses = useCallback(async (stationList: Station[]) => {
    const records = await Promise.all(
      stationList.map((station) => api.stationStatus(station.properties.station_id)),
    );
    setStatuses(Object.fromEntries(records.map((status) => [status.station_id, status])));
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
      setStations(stationList);
      setVehicles(vehicleList);
      setModelStatus(model);
      setVehicleId((current) => current || vehicleList[0].vehicle_id);
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

  const selectRecommendation = useCallback((item: RecommendationItem) => {
    setSelectedStationId(item.station_id);
    setRoute(item.route);
  }, []);

  const submitJourney = async () => {
    if (!vehicleId || !originValid || !destinationValid) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.searchRoute({
        origin,
        destination,
        vehicle_id: vehicleId,
        battery_pct: Math.round(initialSoc * 100),
      });
      setRecommendation(result);
      await refreshStatuses(stations);
      if (result.recommendations.length) {
        selectRecommendation(result.recommendations[0]);
      } else {
        setSelectedStationId(null);
        setRoute(result.direct_route);
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
  const selectedRecommendation =
    recommendation?.recommendations.find((item) => item.station_id === selectedStationId) ?? null;
  const notice = useMemo(() => {
    if (!recommendation) return null;
    if (recommendation.case === "enough") {
      return `Pin đủ để tới điểm đến (${Math.round(recommendation.direct_min)} phút), không cần sạc.`;
    }
    if (recommendation.case === "fallback") {
      const nearest = recommendation.nearest_station_name
        ? `Trạm gần nhất: ${recommendation.nearest_station_name}.`
        : "";
      const missing =
        recommendation.missing_km != null
          ? ` Còn thiếu khoảng ${Math.round(recommendation.missing_km)} km để tới trạm.`
          : "";
      return `Pin không đủ tới trạm nào. ${nearest}${missing}`.trim();
    }
    return null;
  }, [recommendation]);
  const handleStationSelect = useCallback((stationId: string) => setSelectedStationId(stationId), []);
  const handleProviderChange = useCallback(
    (provider: "goong" | "osm") => setMapProvider(provider),
    [],
  );
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
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Smart EV Journey">
          <span className="brand-mark">EV</span>
          <span><strong>Smart EV Journey</strong><small>HCMC charging navigator</small></span>
        </a>
        <StatusBar model={modelStatus} mapProvider={mapProvider} />
      </header>

      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(null)}>Đóng</button></div>}
      {modelStatus && !modelStatus.release_ready && (
        <div className="fallback-banner" role="status">
          Occupancy model chưa sẵn sàng — backend đang dùng {modelStatus.prediction_source === "default" ? "giá trị mặc định cố định" : "persistence fallback"}.
        </div>
      )}

      <div className="workspace" id="top">
        <section className="control-column">
          <JourneyForm
            vehicles={vehicles}
            vehicleId={vehicleId}
            initialSoc={initialSoc}
            origin={origin}
            destination={destination}
            locationsValid={originValid && destinationValid}
            submitting={submitting}
            onVehicleChange={setVehicleId}
            onInitialSocChange={setInitialSoc}
            onOriginChange={setOrigin}
            onDestinationChange={setDestination}
            onOriginValidityChange={handleOriginValidityChange}
            onDestinationValidityChange={handleDestinationValidityChange}
            onSubmit={() => void submitJourney()}
          />
          <RecommendationList
            items={recommendation?.recommendations ?? []}
            exclusions={recommendation?.excluded_candidates ?? []}
            stations={stations}
            vehicle={selectedVehicle}
            selectedStationId={selectedStationId}
            hasRun={recommendation !== null}
            notice={notice}
            onSelect={selectRecommendation}
          />
        </section>

        <section className="map-column">
          <div className="map-header">
            <div><span className="step-label">03 · Bản đồ</span><h2>Tuyến đường và trạng thái trạm</h2></div>
            <div className="map-legend">
              <span><i className="legend-dot available" />Còn trống</span>
              <span><i className="legend-dot busy" />Bận / có queue</span>
              <span><i className="legend-dot offline" />Offline / chưa rõ</span>
            </div>
          </div>
          <div className="map-frame">
            <MapView
              stations={stations}
              statuses={statuses}
              route={route}
              selectedStationId={selectedStationId}
              onStationSelect={handleStationSelect}
              onProviderChange={handleProviderChange}
            />
            <span className="map-provider-chip">{mapProvider === "goong" ? "Goong Maps" : "Leaflet · OSM fallback"}</span>
          </div>
          <StationDetails
            station={selectedStation}
            status={selectedStationId ? statuses[selectedStationId] ?? null : null}
            recommendation={selectedRecommendation}
          />
        </section>
      </div>
    </main>
  );
}
