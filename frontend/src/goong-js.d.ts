declare module "@goongmaps/goong-js" {
  export interface GoongSource {
    setData(data: unknown): void;
  }

  export interface GoongMap {
    on(event: string, handler: (event?: unknown) => void): void;
    addControl(control: unknown, position?: string): void;
    addSource(id: string, source: unknown): void;
    addLayer(layer: unknown): void;
    getSource(id: string): GoongSource | undefined;
    getLayer(id: string): unknown;
    getBounds(): {
      getWest(): number;
      getSouth(): number;
      getEast(): number;
      getNorth(): number;
    };
    removeLayer(id: string): void;
    removeSource(id: string): void;
    remove(): void;
  }

  export interface GoongMarker {
    setLngLat(coordinates: [number, number]): GoongMarker;
    addTo(map: GoongMap): GoongMarker;
    remove(): void;
  }

  export interface GoongStatic {
    accessToken: string;
    supported(): boolean;
    Map: new (options: Record<string, unknown>) => GoongMap;
    Marker: new (element?: HTMLElement) => GoongMarker;
    NavigationControl: new () => unknown;
  }

  const goongjs: GoongStatic;
  export default goongjs;
}
