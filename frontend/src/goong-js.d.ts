declare module "@goongmaps/goong-js" {
  interface GoongSource {
    setData(data: unknown): void;
  }

  interface GoongMap {
    on(event: string, handler: (event?: unknown) => void): void;
    off(event: string, handler: (event?: unknown) => void): void;
    getCanvas(): HTMLCanvasElement;
    addControl(control: unknown, position?: string): void;
    addSource(id: string, source: unknown): void;
    addLayer(layer: unknown): void;
    getSource(id: string): GoongSource | undefined;
    getLayer(id: string): unknown;
    flyTo(options: Record<string, unknown>): void;
    removeLayer(id: string): void;
    removeSource(id: string): void;
    remove(): void;
  }

  interface GoongMarker {
    setLngLat(coordinates: [number, number]): GoongMarker;
    addTo(map: GoongMap): GoongMarker;
    remove(): void;
  }

  interface GoongStatic {
    accessToken: string;
    supported(): boolean;
    Map: new (options: Record<string, unknown>) => GoongMap;
    Marker: new (element?: HTMLElement) => GoongMarker;
    NavigationControl: new () => unknown;
  }

  const goongjs: GoongStatic;
  export default goongjs;
}
