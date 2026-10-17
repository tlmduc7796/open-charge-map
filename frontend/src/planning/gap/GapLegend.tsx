import { RAMP, TRAFFIC_RAMP, formatNumber, layerRange, roadFlowRange, type CellView, type GapLayer } from "./gapFormat";
import type { GapRoadItem } from "./gapTypes";

export default function GapLegend({ layer, views, roads }: { layer: GapLayer; views: CellView[]; roads: GapRoadItem[] }) {
  if (layer === "flow") {
    const [roadLow, roadHigh] = roadFlowRange(roads);
    return (
      <div className="gap-legend" aria-label="Chú giải bản đồ">
        <b>Lưu lượng tuyến đường (xe/giờ)</b>
        <div className="gap-legend-ramp" style={{ background: `linear-gradient(90deg, ${TRAFFIC_RAMP.join(", ")})` }} />
        <div className="gap-legend-scale"><span>{formatNumber(roadLow, 0)} · thông thoáng</span><span>{formatNumber(roadHigh, 0)} · kẹt</span></div>
        <div className="gap-legend-items">
          <span><i className="swatch dashed" />Gần trạm của mình</span>
          <span><i className="swatch ring" />Cụm của ứng viên đang chọn</span>
        </div>
      </div>
    );
  }
  const [low, high] = layerRange(layer, views);
  return (
    <div className="gap-legend" aria-label="Chú giải bản đồ">
      <b>{layer === "rent" ? "Giá nhà (nghìn đ/m²/tháng)" : layer === "score" ? "Điểm dự đoán" : "Giá trị lớp đang xem"}</b>
      <div className="gap-legend-ramp" style={{ background: `linear-gradient(90deg, ${RAMP.join(", ")})` }} />
      <div className="gap-legend-scale"><span>{formatNumber(low, high < 1 ? 4 : 1)}</span><span>{formatNumber(high, high < 1 ? 4 : 1)}</span></div>
      <div className="gap-legend-items">
        <span><i className="swatch grey" />Ô bị loại</span>
        <span><i className="swatch dashed" />Gần trạm của mình</span>
        <span><i className="swatch ring" />Cụm của ứng viên đang chọn</span>
      </div>
    </div>
  );
}
