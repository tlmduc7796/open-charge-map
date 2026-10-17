import { useCallback, useState } from "react";

import GapGoongMap from "./GapGoongMap";
import GapLeafletMap from "./GapLeafletMap";
import type { GapMapProps } from "./gapGeo";

/** Goong basemap when VITE_GOONG_MAPTILES_KEY is set and loads; OpenStreetMap otherwise. */
export default function GapMap(props: GapMapProps) {
  const hasGoongKey = Boolean(import.meta.env.VITE_GOONG_MAPTILES_KEY);
  const [useFallback, setUseFallback] = useState(!hasGoongKey);
  const handleFailure = useCallback(() => setUseFallback(true), []);
  return useFallback ? <GapLeafletMap {...props} /> : <GapGoongMap {...props} onFailure={handleFailure} />;
}
