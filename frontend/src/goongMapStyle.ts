import type goongjs from "@goongmaps/goong-js";

/**
 * Goong's base style ships amenity icons (restaurants, shops, cafés, …) baked
 * into the vector tiles as "poi-*" layers. We only want our own station
 * markers on the map, so hide every POI layer once the style has loaded.
 */
export function hideGoongPoiLayers(map: InstanceType<typeof goongjs.Map>) {
  const layers = map.getStyle()?.layers ?? [];
  for (const layer of layers) {
    if (layer.id.startsWith("poi-")) {
      map.setLayoutProperty(layer.id, "visibility", "none");
    }
  }
}

const ICON_RASTER_SIZE = 64;

/**
 * Rasterizes an SVG path into a white-on-transparent image and registers it
 * with the map as an SDF icon, so a GL symbol layer can recolor it per
 * feature via `icon-color`. A symbol layer may reference the icon id before
 * this resolves — mapbox-gl-js (which goong-js forks) simply skips drawing
 * symbols for an unregistered image until `addImage` is called, so callers
 * don't need to wait on this before adding their layer.
 */
export function loadSdfIcon(map: InstanceType<typeof goongjs.Map>, id: string, svgPath: string): Promise<void> {
  if (map.hasImage(id)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON_RASTER_SIZE}" height="${ICON_RASTER_SIZE}" ` +
      `viewBox="0 0 24 24"><path fill="#fff" d="${svgPath}"/></svg>`;
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = ICON_RASTER_SIZE;
      canvas.height = ICON_RASTER_SIZE;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("2d canvas context unavailable"));
        return;
      }
      ctx.drawImage(image, 0, 0, ICON_RASTER_SIZE, ICON_RASTER_SIZE);
      map.addImage(id, ctx.getImageData(0, 0, ICON_RASTER_SIZE, ICON_RASTER_SIZE), { sdf: true });
      resolve();
    };
    image.onerror = () => reject(new Error(`Failed to rasterize icon "${id}"`));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  });
}
