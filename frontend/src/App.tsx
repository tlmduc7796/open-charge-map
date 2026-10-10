import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import JourneyForm from "./components/JourneyForm";
import RecommendationList from "./components/RecommendationList";
import QueueLab from "./components/QueueLab";
import StationDetails from "./components/StationDetails";
import StatusBar from "./components/StatusBar";
import type {
  DemoScenario,
  GeoPoint,
  JourneyRecommendation,
  JourneyRequest,
  ModelStatus,
  PlannedArrival,
  RecommendationItem,
  RouteResult,
  Station,
  StationIncidentType,
  StationOccupancyForecast,
  StationOccupancyObservation,
  StationBounds,
  StationStatus,
  Vehicle,
} from "./types";

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== "false";
const MapView = lazy(() => import("./components/MapView"));
const CURRENT_JOURNEY_KEY = "smart-ev-current-journey-id";
const DEFAULT_ORIGIN: GeoPoint = { lat: 10.7769, lon: 106.7008, label: "Điểm đi" };
const DEFAULT_DESTINATION: GeoPoint = { lat: 10.8231, lon: 106.6297, label: "Điểm đến" };

export default function App() {
  const [stations, setStations] = useState<Station[]>([]);
  const [pinnedStation, setPinnedStation] = useState<Station | null>(null);
  const [statuses, setStatuses] = useState<Record<string, StationStatus>>({});
  const [forecastState, setForecastState] = useState<{
    stationId: string;
    forecast: StationOccupancyForecast | null;
    unavailable: boolean;
  } | null>(null);
  const [historyState, setHistoryState] = useState<{
    stationId: string;
    observations: StationOccupancyObservation[] | null;
    unavailable: boolean;
  } | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [statusFeedUnavailable, setStatusFeedUnavailable] = useState(false);
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
  const [initialLoadFailed, setInitialLoadFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [updatingPosition, setUpdatingPosition] = useState(false);
  const [journeyBatteryPct, setJourneyBatteryPct] = useState<number | null>(null);
  const [activeArrival, setActiveArrival] = useState<PlannedArrival | null>(null);
  const pendingArrivalCommit = useRef<{
    signature: string;
    payload: Parameters<typeof api.commitArrival>[0];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastRealtimeRecoveryAt = useRef(0);
  const stationBoundsTimer = useRef<number | null>(null);
  const stationBoundsKey = useRef("");
  const stationBoundsGeneration = useRef(0);
  const pinnedStationRef = useRef<Station | null>(null);
  const pendingJourneyRequest = useRef<{
    intent: string;
    payload: JourneyRequest;
  } | null>(null);

  const scenario = scenarios.find((item) => item.scenario_id === scenarioId) ?? scenarios[0] ?? null;

  useEffect(() => {
    pinnedStationRef.current = pinnedStation;
  }, [pinnedStation]);

  const cancelArrivalRecord = (arrival: PlannedArrival) =>
    api.cancelArrival(
      arrival.arrival_id,
      arrival.journey_id,
      recommendation?.journey_access_token,
    );

  const refreshStatuses = useCallback(async (stationList: Station[]) => {
    const stationIds = stationList.map((station) => station.properties.station_id);
    if (!stationIds.length) {
      setStatuses({});
      setStatusFeedUnavailable(false);
      return;
    }
    try {
      const records = await api.stationStatuses(stationIds);
      setStatuses(Object.fromEntries(records.map((status) => [status.station_id, status])));
      setStatusFeedUnavailable(false);
    } catch (caught) {
      setStatusFeedUnavailable(true);
      setStatuses((current) => Object.fromEntries(
        Object.entries(current).map(([stationId, status]) => [
          stationId,
          { ...status, is_stale: true },
        ]),
      ));
      throw caught;
    }
  }, []);

  const loadStationsWithinBounds = useCallback((bounds: StationBounds) => {
    const key = [bounds.west, bounds.south, bounds.east, bounds.north]
      .map((value) => value.toFixed(3))
      .join(":");
    if (key === stationBoundsKey.current) return;
    stationBoundsKey.current = key;
    const generation = ++stationBoundsGeneration.current;
    if (stationBoundsTimer.current !== null) {
      window.clearTimeout(stationBoundsTimer.current);
    }
    stationBoundsTimer.current = window.setTimeout(() => {
      void (async () => {
        try {
          const pinned = pinnedStationRef.current;
          const stationList = await api.stationsInBounds(bounds, pinned ? 199 : 200);
          const visibleStations = pinned && !stationList.some(
            (station) => station.properties.station_id === pinned.properties.station_id,
          ) ? [...stationList, pinned] : stationList;
          const records = visibleStations.length
            ? await api.stationStatuses(
                visibleStations.map((station) => station.properties.station_id),
              )
            : [];
          if (generation !== stationBoundsGeneration.current) return;
          setStations(stationList);
          setStatuses(Object.fromEntries(records.map((status) => [status.station_id, status])));
          setStatusFeedUnavailable(false);
        } catch (caught) {
          if (generation !== stationBoundsGeneration.current) return;
          stationBoundsKey.current = "";
          setStations([]);
          setStatusFeedUnavailable(true);
          setStatuses((current) => Object.fromEntries(
            Object.entries(current).map(([stationId, status]) => [
              stationId,
              { ...status, is_stale: true },
            ]),
          ));
          setError(caught instanceof Error ? caught.message : "Không thể tìm trạm trong vùng bản đồ.");
        }
      })();
    }, 250);
  }, []);

  const displayedStations = useMemo(() => {
    if (!pinnedStation || selectedStationId !== pinnedStation.properties.station_id || stations.some(
      (station) => station.properties.station_id === pinnedStation.properties.station_id,
    )) return stations;
    return [...stations, pinnedStation];
  }, [pinnedStation, selectedStationId, stations]);

  const loadInitialData = useCallback(async () => {
    setLoading(true);
    setInitialLoadFailed(false);
    setError(null);
    try {
      const initialBounds: StationBounds = {
        west: 106.4,
        south: 10.4,
        east: 107.1,
        north: 11.2,
      };
      const [stationList, vehicleList, scenarioList, model] = await Promise.all([
        api.stationsInBounds(initialBounds),
        api.vehicles(),
        DEMO_MODE ? api.scenarios() : Promise.resolve([]),
        api.modelStatus(),
      ]);
      if (DEMO_MODE && !scenarioList.length) throw new Error("Backend không có demo scenario.");
      setStations(stationList);
      setVehicles(vehicleList);
      setScenarios(scenarioList);
      setModelStatus(model);
      const defaultScenario = scenarioList[0];
      if (defaultScenario) {
        setScenarioId(defaultScenario.scenario_id);
        setVehicleId(defaultScenario.vehicle_id);
        setInitialSoc(defaultScenario.initial_soc);
        setTargetSoc(defaultScenario.target_soc);
        setOrigin(defaultScenario.origin);
        setDestination(defaultScenario.destination);
      } else {
        const defaultVehicle = vehicleList[0];
        if (!defaultVehicle) throw new Error("Backend không có hồ sơ xe khả dụng.");
        setVehicleId(defaultVehicle.vehicle_id);
        setInitialSoc(0.5);
        setTargetSoc(defaultVehicle.default_target_soc);
        setOrigin(DEFAULT_ORIGIN);
        setDestination(DEFAULT_DESTINATION);
      }
      await refreshStatuses(stationList);
      if (!DEMO_MODE) {
        try {
          const journeyId = sessionStorage.getItem(CURRENT_JOURNEY_KEY);
          const accessToken = journeyId
            ? sessionStorage.getItem(`journey-token:${journeyId}`)
            : null;
          if (journeyId && accessToken) {
            const stored = await api.getJourney(journeyId, accessToken);
            const restored: JourneyRecommendation = {
              ...stored.recommendation,
              journey_access_token: accessToken,
            };
            setRecommendation(restored);
            setActiveArrival(stored.active_planned_arrival ?? null);
            setVehicleId(stored.request.vehicle_id);
            setInitialSoc(stored.request.initial_soc ?? 0.5);
            setTargetSoc(
              stored.request.target_soc
                ?? vehicleList.find((vehicle) => vehicle.vehicle_id === stored.request.vehicle_id)
                  ?.default_target_soc
                ?? 0.8,
            );
            if (stored.request.origin) setOrigin(stored.request.origin);
            if (stored.request.destination) setDestination(stored.request.destination);
            const selected = restored.recommendations[0];
            setSelectedStationId(selected?.station_id ?? null);
            setRoute(selected?.route ?? restored.direct_route);
          }
        } catch (caught) {
          setError(
            caught instanceof Error
              ? `Không thể khôi phục hành trình đã lưu: ${caught.message}`
              : "Không thể khôi phục hành trình đã lưu.",
          );
        }
      }
    } catch (caught) {
      setInitialLoadFailed(true);
      setError(caught instanceof Error ? caught.message : "Không thể tải dữ liệu backend.");
    } finally {
      setLoading(false);
    }
  }, [refreshStatuses]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadInitialData(), 0);
    return () => window.clearTimeout(timer);
  }, [loadInitialData]);

  useEffect(() => {
    if (loading || displayedStations.length === 0) return;
    const stationIds = displayedStations.map((station) => station.properties.station_id).sort();
    if (typeof EventSource === "undefined") {
      const timer = window.setInterval(() => {
        void refreshStatuses(displayedStations).catch(() => undefined);
      }, 30_000);
      return () => window.clearInterval(timer);
    }
    const stream = new EventSource(api.realtimeStatusEventsUrl(stationIds));
    stream.addEventListener("station_status", (event) => {
      try {
        const records = JSON.parse((event as MessageEvent<string>).data) as StationStatus[];
        setStatuses(Object.fromEntries(records.map((status) => [status.station_id, status])));
        setStatusFeedUnavailable(false);
      } catch {
        // Ignore a malformed event and let EventSource reconnect/fallback recovery run.
      }
    });
    stream.onerror = () => {
      const now = Date.now();
      if (now - lastRealtimeRecoveryAt.current < 30_000) return;
      lastRealtimeRecoveryAt.current = now;
      void refreshStatuses(displayedStations).catch(() => undefined);
    };
    return () => stream.close();
  }, [displayedStations, loading, refreshStatuses]);

  useEffect(() => {
    if (!selectedStationId) return;
    const visible = stations.find(
      (station) => station.properties.station_id === selectedStationId,
    );
    if (visible) return;
    if (pinnedStation?.properties.station_id === selectedStationId) return;
    let active = true;
    void api.station(selectedStationId).then(async (station) => {
      if (!active) return;
      setPinnedStation(station);
      const records = await api.stationStatuses([selectedStationId]);
      if (active && records.length) {
        setStatuses((current) => ({ ...current, [selectedStationId]: records[0] }));
      }
    }).catch(() => {
      if (active) setPinnedStation(null);
    });
    return () => { active = false; };
  }, [pinnedStation, selectedStationId, stations]);

  const selectedStatusTimestamp = selectedStationId
    ? statuses[selectedStationId]?.timestamp
    : undefined;
  const selectedForecast = forecastState?.stationId === selectedStationId
    ? forecastState.forecast
    : null;
  const forecastUnavailable = forecastState?.stationId === selectedStationId
    ? forecastState.unavailable
    : false;
  const selectedHistory = historyState?.stationId === selectedStationId
    ? historyState.observations
    : null;
  const historyUnavailable = historyState?.stationId === selectedStationId
    ? historyState.unavailable
    : false;
  useEffect(() => {
    if (!selectedStationId) return;
    const stationId = selectedStationId;
    let active = true;
    void api.stationForecast(stationId, 15).then((forecast) => {
      if (active) setForecastState({ stationId, forecast, unavailable: false });
    }).catch(() => {
      if (active) setForecastState({ stationId, forecast: null, unavailable: true });
    });
    return () => { active = false; };
  }, [selectedStationId, selectedStatusTimestamp]);

  useEffect(() => {
    if (!selectedStationId) return;
    const stationId = selectedStationId;
    let active = true;
    void api.stationHistory(stationId).then((observations) => {
      if (active) setHistoryState({ stationId, observations, unavailable: false });
    }).catch(() => {
      if (active) setHistoryState({ stationId, observations: null, unavailable: true });
    });
    return () => { active = false; };
  }, [selectedStationId, selectedStatusTimestamp]);

  const changeScenario = (nextScenarioId: string) => {
    const next = scenarios.find((item) => item.scenario_id === nextScenarioId);
    if (!next) return;
    if (activeArrival?.status === "planned") {
      void cancelArrivalRecord(activeArrival).catch(() => undefined);
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
    setJourneyBatteryPct(null);
  };

  const selectRecommendation = useCallback(
    async (item: RecommendationItem) => {
      setSelectedStationId(item.station_id);
      setRoute(item.route);
    },
    [],
  );

  const submitJourney = async () => {
    if ((DEMO_MODE && !scenario) || !vehicleId || !origin || !destination || !originValid || !destinationValid) return;
    setSubmitting(true);
    setError(null);
    const candidateRequest: JourneyRequest = {
      ...(DEMO_MODE && scenario ? { scenario_id: scenario.scenario_id } : {}),
      apply_scenario_events: DEMO_MODE && applyEvents,
      vehicle_id: vehicleId,
      initial_soc: initialSoc,
      target_soc: targetSoc,
      origin,
      destination,
      departure_at: new Date().toISOString(),
    };
    const intent = JSON.stringify(
      candidateRequest,
      (key, value: unknown) => key === "departure_at" ? undefined : value,
    );
    const requestPayload = pendingJourneyRequest.current?.intent === intent
      ? pendingJourneyRequest.current.payload
      : candidateRequest;
    pendingJourneyRequest.current = { intent, payload: requestPayload };
    try {
      if (activeArrival?.status === "planned") {
        await cancelArrivalRecord(activeArrival);
        setActiveArrival(null);
      }
      const result = await api.recommend(requestPayload);
      pendingJourneyRequest.current = null;
      setRecommendation(result);
      if (!DEMO_MODE && result.journey_id) {
        try {
          sessionStorage.setItem(CURRENT_JOURNEY_KEY, result.journey_id);
        } catch {
          // The journey remains available in backend persistence for this session.
        }
      }
      setJourneyBatteryPct(null);
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

  const updateJourneyPosition = async () => {
    if (!recommendation?.journey_id || !navigator.geolocation) {
      setError("GPS không khả dụng hoặc hành trình chưa được lưu.");
      return;
    }
    if (journeyBatteryPct === null) {
      setError("Nhập SOC hiện tại của xe trước khi gửi GPS và kiểm tra re-plan.");
      return;
    }
    let accessToken = recommendation.journey_access_token ?? null;
    if (!accessToken) {
      try {
        accessToken = sessionStorage.getItem(`journey-token:${recommendation.journey_id}`);
      } catch {
        accessToken = null;
      }
    }
    if (!accessToken) {
      setError("Không tìm thấy quyền truy cập hành trình trong phiên này.");
      return;
    }
    setUpdatingPosition(true);
    setError(null);
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 15_000,
          maximumAge: 0,
        });
      });
      const result = await api.recordJourneyPosition(recommendation.journey_id, {
        recorded_at: new Date(position.timestamp).toISOString(),
        location: {
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          label: "Vị trí hiện tại",
        },
        battery_pct: journeyBatteryPct,
      }, accessToken);
      setJourneyBatteryPct(null);
      if (result.recommendation) {
        setRecommendation({ ...result.recommendation, journey_access_token: accessToken });
        if (result.recommendation.recommendations.length) {
          await selectRecommendation(result.recommendation.recommendations[0]);
        } else {
          setSelectedStationId(null);
          setRoute(result.recommendation.direct_route);
        }
        await refreshStatuses(stations);
      } else if (result.position.off_route && !result.position.replan_suggested) {
        setError("Vị trí đã được lưu; re-plan đang chờ hết khoảng ổn định để tránh đổi trạm liên tục.");
      } else if (result.replan_reason === "BATTERY_LEVEL_REQUIRED") {
        setError("Cần cập nhật SOC hiện tại trước khi tính lại hành trình.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể cập nhật GPS hành trình.");
    } finally {
      setUpdatingPosition(false);
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
      setJourneyBatteryPct(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể reset demo.");
    }
  };

  const commitRecommendation = async () => {
    if (!selectedRecommendation) return;
    if (!DEMO_MODE && (!recommendation?.journey_id || !recommendation.journey_access_token)) {
      setError("Không có quyền truy cập journey để xác nhận planned arrival.");
      return;
    }
    setCommitting(true);
    setError(null);
    try {
      if (activeArrival?.status === "planned") {
        await cancelArrivalRecord(activeArrival);
        setActiveArrival(null);
      }
      const commitData = {
        journey_id: recommendation?.journey_id,
        station_id: selectedRecommendation.station_id,
        vehicle_id: vehicleId,
        route_id: selectedRecommendation.route_id,
        route_duration_to_station_s: selectedRecommendation.route_duration_to_station_s,
        expected_energy_kwh: selectedRecommendation.energy_to_add_kwh,
        expected_charge_duration_min: selectedRecommendation.estimated_charge_min,
      };
      const signature = JSON.stringify(commitData);
      if (pendingArrivalCommit.current?.signature !== signature) {
        pendingArrivalCommit.current = {
          signature,
          payload: {
            ...commitData,
            arrival_id: crypto.randomUUID(),
            departure_at: new Date().toISOString(),
          },
        };
      }
      const arrival = await api.commitArrival(
        pendingArrivalCommit.current.payload,
        recommendation?.journey_access_token,
      );
      pendingArrivalCommit.current = null;
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
      setActiveArrival(await cancelArrivalRecord(activeArrival));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể hủy tuyến.");
    } finally {
      setCommitting(false);
    }
  };

  const reportStationIncident = async (
    stationId: string,
    incidentType: StationIncidentType,
    description: string,
    idempotencyKey: string,
  ) => {
    if (!recommendation?.journey_id || !recommendation.journey_access_token) {
      throw new Error("Không tìm thấy quyền báo cáo cho hành trình này.");
    }
    setError(null);
    try {
      await api.reportStationIncident(stationId, recommendation.journey_access_token, {
        journey_id: recommendation.journey_id,
        idempotency_key: idempotencyKey,
        incident_type: incidentType,
        description,
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Không gửi được báo cáo trạm.";
      setError(message);
      throw caught;
    }
  };

  const selectedStation = useMemo(
    () => displayedStations.find((item) => item.properties.station_id === selectedStationId) ?? null,
    [displayedStations, selectedStationId],
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

  if (DEMO_MODE && !scenario) {
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
          demoMode={DEMO_MODE}
          model={modelStatus}
          mapProvider={mapProvider}
          activeEvents={recommendation?.active_event_ids ?? []}
          statusFeedUnavailable={statusFeedUnavailable}
        />
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          {initialLoadFailed && !DEMO_MODE && (
            <button type="button" onClick={() => void loadInitialData()}>Thử tải lại</button>
          )}
          <button type="button" onClick={() => setError(null)}>Đóng</button>
        </div>
      )}
      {modelStatus && !modelStatus.release_ready && (
        <div className="fallback-banner" role="status">
          Occupancy model chưa có bản release đã xác thực — backend đang dùng persistence fallback.
          {modelStatus.flags.length ? ` (${modelStatus.flags.join(", ")})` : ""}
        </div>
      )}

      <div className="workspace" id="top">
        <section className="control-column">
          <JourneyForm
            demoMode={DEMO_MODE}
            scenarios={scenarios}
            vehicles={vehicles}
            scenario={scenario}
            vehicleId={vehicleId}
            initialSoc={initialSoc}
            targetSoc={targetSoc}
            applyEvents={applyEvents}
            origin={origin ?? scenario?.origin ?? DEFAULT_ORIGIN}
            destination={destination ?? scenario?.destination ?? DEFAULT_DESTINATION}
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
          {!DEMO_MODE && recommendation?.journey_id && (
            <div className="journey-position-controls">
              <label>
                SOC hiện tại để kiểm tra re-plan (%)
                <input
                  aria-label="SOC hiện tại để kiểm tra re-plan"
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  inputMode="numeric"
                  placeholder="Nhập SOC hiện tại"
                  value={journeyBatteryPct ?? ""}
                  disabled={updatingPosition || submitting}
                  onChange={(event) => {
                    const value = event.target.value;
                    const parsed = value === "" ? null : Number(value);
                    setJourneyBatteryPct(
                      parsed !== null && Number.isFinite(parsed) && parsed >= 0 && parsed <= 100
                        ? parsed
                        : null,
                    );
                  }}
                />
              </label>
              <button
                className="secondary-button gps-update-button"
                type="button"
                disabled={updatingPosition || submitting || journeyBatteryPct === null}
                onClick={() => void updateJourneyPosition()}
              >
              {updatingPosition ? "Đang cập nhật vị trí…" : "Cập nhật GPS và tính lại nếu lệch tuyến"}
              </button>
            </div>
          )}
          <RecommendationList
            items={recommendation?.recommendations ?? []}
            outcome={recommendation?.outcome ?? null}
            exclusions={recommendation?.excluded_candidates ?? []}
            fallbackCandidate={recommendation?.fallback_candidate}
            resultFlags={recommendation?.flags ?? []}
            candidateLimit={recommendation?.candidate_limit}
            stations={displayedStations}
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
              {DEMO_MODE && <span><i className="legend-dot affected" />Event</span>}
              <span><i className="legend-dot offline" />Offline</span>
              <span><i className="legend-dot unknown" />Chưa rõ</span>
            </div>
          </div>
          <div className="map-frame">
            <Suspense fallback={<div className="map-loading" role="status">Loading map…</div>}>
              <MapView
                stations={displayedStations}
                statuses={statuses}
                route={route}
                selectedStationId={selectedStationId}
                onStationSelect={handleStationSelect}
                onProviderChange={handleProviderChange}
                onViewportChange={loadStationsWithinBounds}
              />
            </Suspense>
            <span className="map-provider-chip">{mapProvider === "goong" ? "Goong Maps" : "Leaflet · OSM fallback"}</span>
          </div>
          <StationDetails
            demoMode={DEMO_MODE}
            station={selectedStation}
            status={selectedStationId ? statuses[selectedStationId] ?? null : null}
            forecast={selectedForecast}
            forecastUnavailable={forecastUnavailable}
            history={selectedHistory}
            historyUnavailable={historyUnavailable}
            recommendation={selectedRecommendation}
            activeArrival={activeArrival}
            committing={committing}
            journeyId={recommendation?.journey_id ?? null}
            journeyAccessToken={recommendation?.journey_access_token ?? null}
            onReportIncident={reportStationIncident}
            onCommit={() => void commitRecommendation()}
            onCancel={() => void cancelArrival()}
          />
        </section>
      </div>
      {DEMO_MODE && <QueueLab />}
    </main>
  );
}
