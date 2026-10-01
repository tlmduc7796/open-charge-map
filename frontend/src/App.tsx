import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import JourneyForm from "./components/JourneyForm";
import MapView from "./components/MapView";
import RecommendationList from "./components/RecommendationList";
import QueueLab from "./components/QueueLab";
import StationDetails from "./components/StationDetails";
import StatusBar from "./components/StatusBar";
import type {
  DemoScenario,
  GeoPoint,
  JourneyRecommendation,
  ModelStatus,
  PlannedArrival,
  RecommendationItem,
  RouteResult,
  Station,
  StationStatus,
  Vehicle,
} from "./types";

export default function App() {
  const [stations, setStations] = useState<Station[]>([]);
  const [statuses, setStatuses] = useState<Record<string, StationStatus>>({});
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [scenarioId, setScenarioId] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [initialSoc, setInitialSoc] = useState(0.5);
  const [targetSoc, setTargetSoc] = useState(0.8);
  const [applyEvents, setApplyEvents] = useState(false);
  const [origin, setOrigin] = useState<GeoPoint | null>(null);
  const [destination, setDestination] = useState<GeoPoint | null>(null);
  const [originValid, setOriginValid] = useState(true);
  const [destinationValid, setDestinationValid] = useState(true);
  const [recommendation, setRecommendation] = useState<JourneyRecommendation | null>(null);
  const [route, setRoute] = useState<RouteResult | null>(null);
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [mapProvider, setMapProvider] = useState<"goong" | "osm">("goong");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [activeArrival, setActiveArrival] = useState<PlannedArrival | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scenario = scenarios.find((item) => item.scenario_id === scenarioId) ?? scenarios[0];

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
      const [stationList, vehicleList, scenarioList, model] = await Promise.all([
        api.stations(),
        api.vehicles(),
        api.scenarios(),
        api.modelStatus(),
      ]);
      if (!scenarioList.length) throw new Error("Backend không có demo scenario.");
      setStations(stationList);
      setVehicles(vehicleList);
      setScenarios(scenarioList);
      setModelStatus(model);
      const defaultScenario = scenarioList[0];
      setScenarioId(defaultScenario.scenario_id);
      setVehicleId(defaultScenario.vehicle_id);
      setInitialSoc(defaultScenario.initial_soc);
      setTargetSoc(defaultScenario.target_soc);
      setOrigin(defaultScenario.origin);
      setDestination(defaultScenario.destination);
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

  const changeScenario = (nextScenarioId: string) => {
    const next = scenarios.find((item) => item.scenario_id === nextScenarioId);
    if (!next) return;
    if (activeArrival?.status === "planned") {
      void api.cancelArrival(activeArrival.arrival_id).catch(() => undefined);
    }
    setScenarioId(next.scenario_id);
    setVehicleId(next.vehicle_id);
    setInitialSoc(next.initial_soc);
    setTargetSoc(next.target_soc);
    setOrigin(next.origin);
    setDestination(next.destination);
    setOriginValid(true);
    setDestinationValid(true);
    setApplyEvents(false);
    setRecommendation(null);
    setRoute(null);
    setSelectedStationId(null);
    setActiveArrival(null);
  };

  const selectRecommendation = useCallback(
    async (item: RecommendationItem) => {
      setSelectedStationId(item.station_id);
      setRoute(item.route);
    },
    [],
  );

  const submitJourney = async () => {
    if (!scenario || !origin || !destination || !originValid || !destinationValid) return;
    setSubmitting(true);
    setError(null);
    try {
      if (activeArrival?.status === "planned") {
        await api.cancelArrival(activeArrival.arrival_id);
        setActiveArrival(null);
      }
      const result = await api.recommend({
        scenario_id: scenario.scenario_id,
        apply_scenario_events: applyEvents,
        vehicle_id: vehicleId,
        initial_soc: initialSoc,
        target_soc: targetSoc,
        origin,
        destination,
        departure_at: new Date().toISOString(),
      });
      setRecommendation(result);
      await refreshStatuses(stations);
      if (result.recommendations.length) {
        await selectRecommendation(result.recommendations[0]);
      } else {
        setSelectedStationId(null);
        setRoute(result.direct_route);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể tạo recommendation.");
    } finally {
      setSubmitting(false);
    }
  };

  const resetDemo = async () => {
    setError(null);
    try {
      await api.resetDemo();
      await refreshStatuses(stations);
      setRecommendation(null);
      setRoute(null);
      setSelectedStationId(null);
      setApplyEvents(false);
      setActiveArrival(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể reset demo.");
    }
  };

  const commitRecommendation = async () => {
    if (!selectedRecommendation) return;
    setCommitting(true);
    setError(null);
    try {
      if (activeArrival?.status === "planned") {
        await api.cancelArrival(activeArrival.arrival_id);
      }
      const arrival = await api.commitArrival({
        station_id: selectedRecommendation.station_id,
        vehicle_id: vehicleId,
        departure_at: new Date().toISOString(),
        route_id: selectedRecommendation.route_id,
        route_duration_to_station_s: selectedRecommendation.route_duration_to_station_s,
        expected_energy_kwh: selectedRecommendation.energy_to_add_kwh,
        expected_charge_duration_min: selectedRecommendation.estimated_charge_min,
      });
      setActiveArrival(arrival);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể xác nhận tuyến.");
    } finally {
      setCommitting(false);
    }
  };

  const cancelArrival = async () => {
    if (!activeArrival || activeArrival.status !== "planned") return;
    setCommitting(true);
    try {
      setActiveArrival(await api.cancelArrival(activeArrival.arrival_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể hủy tuyến.");
    } finally {
      setCommitting(false);
    }
  };

  const selectedStation = useMemo(
    () => stations.find((item) => item.properties.station_id === selectedStationId) ?? null,
    [selectedStationId, stations],
  );
  const selectedRecommendation =
    recommendation?.recommendations.find((item) => item.station_id === selectedStationId) ?? null;
  const handleStationSelect = useCallback((stationId: string) => setSelectedStationId(stationId), []);
  const handleProviderChange = useCallback(
    (provider: "goong" | "osm") => setMapProvider(provider),
    [],
  );
  const handleOriginValidityChange = useCallback(
    (valid: boolean) => setOriginValid(valid),
    [],
  );
  const handleDestinationValidityChange = useCallback(
    (valid: boolean) => setDestinationValid(valid),
    [],
  );

  if (loading) {
    return <main className="app-loading"><div className="loader" /><p>Đang kết nối Smart EV backend…</p></main>;
  }

  if (!scenario) {
    return (
      <main className="app-loading error-screen">
        <h1>Không thể khởi tạo demo</h1>
        <p>{error ?? "Không có scenario khả dụng."}</p>
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
        <StatusBar
          model={modelStatus}
          mapProvider={mapProvider}
          activeEvents={recommendation?.active_event_ids ?? []}
        />
      </header>

      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(null)}>Đóng</button></div>}
      {modelStatus && !modelStatus.release_ready && (
        <div className="fallback-banner" role="status">
          Occupancy model chưa có bản release đã xác thực — backend đang dùng persistence fallback cho demo.
          {modelStatus.flags.length ? ` (${modelStatus.flags.join(", ")})` : ""}
        </div>
      )}

      <div className="workspace" id="top">
        <section className="control-column">
          <JourneyForm
            scenarios={scenarios}
            vehicles={vehicles}
            scenario={scenario}
            vehicleId={vehicleId}
            initialSoc={initialSoc}
            targetSoc={targetSoc}
            applyEvents={applyEvents}
            origin={origin ?? scenario.origin}
            destination={destination ?? scenario.destination}
            locationsValid={originValid && destinationValid}
            submitting={submitting}
            onScenarioChange={changeScenario}
            onVehicleChange={setVehicleId}
            onInitialSocChange={setInitialSoc}
            onTargetSocChange={setTargetSoc}
            onApplyEventsChange={setApplyEvents}
            onOriginChange={setOrigin}
            onDestinationChange={setDestination}
            onOriginValidityChange={handleOriginValidityChange}
            onDestinationValidityChange={handleDestinationValidityChange}
            onSubmit={() => void submitJourney()}
            onReset={() => void resetDemo()}
          />
          <RecommendationList
            items={recommendation?.recommendations ?? []}
            exclusions={recommendation?.excluded_candidates ?? []}
            stations={stations}
            selectedStationId={selectedStationId}
            hasRun={recommendation !== null}
            onSelect={(item) => void selectRecommendation(item)}
          />
        </section>

        <section className="map-column">
          <div className="map-header">
            <div><span className="step-label">03 · Bản đồ</span><h2>Tuyến đường và trạng thái trạm</h2></div>
            <div className="map-legend">
              <span><i className="legend-dot available" />Còn trống</span>
              <span><i className="legend-dot busy" />Bận / có queue</span>
              <span><i className="legend-dot affected" />Event</span>
              <span><i className="legend-dot offline" />Offline</span>
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
            activeArrival={activeArrival}
            committing={committing}
            onCommit={() => void commitRecommendation()}
            onCancel={() => void cancelArrival()}
          />
        </section>
      </div>
      <QueueLab />
    </main>
  );
}
