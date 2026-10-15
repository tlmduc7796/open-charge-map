declare module "@goongmaps/goong-js" {
  interface GoongSource {
    setData(data: unknown): void;
  }

  interface GoongMapLayerMouseEvent {
    lngLat: { lat: number; lng: number };
    features?: Array<{ properties: Record<string, unknown> }>;
  }

  interface GoongMap {
    on(event: string, handler: (event?: unknown) => void): void;
    on(event: string, layerId: string, handler: (event: GoongMapLayerMouseEvent) => void): void;
    off(event: string, handler: (event?: unknown) => void): void;
    off(event: string, layerId: string, handler: (event: GoongMapLayerMouseEvent) => void): void;
    getCanvas(): HTMLCanvasElement;
    addControl(control: unknown, position?: string): void;
    addSource(id: string, source: unknown): void;
    addLayer(layer: unknown): void;
    getSource(id: string): GoongSource | undefined;
    getLayer(id: string): unknown;
    getStyle(): { layers?: Array<{ id: string }> } | undefined;
    setLayoutProperty(layerId: string, name: string, value: unknown): void;
    hasImage(id: string): boolean;
    addImage(id: string, image: unknown, options?: Record<string, unknown>): void;
    flyTo(options: Record<string, unknown>): void;
    fitBounds(bounds: [[number, number], [number, number]], options?: Record<string, unknown>): void;
    resize(): this;
    removeLayer(id: string): void;
    removeSource(id: string): void;
    remove(): void;
  }

  interface GoongMarker {
    setLngLat(coordinates: [number, number]): GoongMarker;
    setPopup(popup: GoongPopup): GoongMarker;
    addTo(map: GoongMap): GoongMarker;
    remove(): void;
  }

  interface GoongPopup {
    setLngLat(coordinates: [number, number]): GoongPopup;
    setHTML(html: string): GoongPopup;
    addTo(map: GoongMap): GoongPopup;
    remove(): void;
  }

  interface GoongStatic {
    accessToken: string;
    supported(): boolean;
    Map: new (options: Record<string, unknown>) => GoongMap;
    Marker: new (element?: HTMLElement) => GoongMarker;
    Popup: new (options?: Record<string, unknown>) => GoongPopup;
    NavigationControl: new () => unknown;
  }

  const goongjs: GoongStatic;
  export default goongjs;
}
