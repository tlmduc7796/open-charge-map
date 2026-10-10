# Phase 0 static data sources

Retrieved on: `2026-09-24`
Demo area: central and central-south Ho Chi Minh City.

## Stations

- EV ONE public station list: <https://www.ev1.vn/tin-tuc/he-thong-tram-sac-cong-cong-ev-one>
  - Supplies station names, addresses, operator, AC/DC class, published power and explicitly stated charger counts.
- EV ONE Deutsches Haus announcement: <https://ev1.vn/tin-tuc/ev-one-khanh-thanh-tram-sac-o-to-ien-cong-cong-tai-deutsches-haus-ho-chi-minh-city-ngoi-nha-uc-thanh-pho-ho-chi-minh>
  - Confirms the public station at B3, 33 Lê Duẩn.
- OpenStreetMap Nominatim: <https://nominatim.openstreetmap.org/>
  - Geocodes the official addresses/place names to WGS84 coordinates.

EV ONE does not publish a connector standard and does not always publish the number of DC ports. Those values, and inferred amenities, are listed in each station's `synthetic_fields`.

- EVCS station directory and detail records: <https://evcs.vn/>
  - Supplies the published charger power and count for the promoted VinFast stations at Landmark 81 (HCM0031), Huyền Trân Công Chúa (HCM0653), FGW Đường số 81 (HCM1345), Vincom Đồng Khởi B5/B6 (HCM0030/HCM0160), Quốc lộ 13 (HCM0618), Vincom Cộng Hòa (HCM0038), and La Vela (HCM0462).
  - DC power entries are represented as CCS2 and AC power entries as Type2, following the VinFast charging-standard source listed below.

Where EVCS did not expose an exact matching inventory, `total_ports` and `connectors` remain explicit project assumptions and are listed in `synthetic_fields`; no EVCS port count was inferred from a nearby station.

The Audi Ho Chi Minh station was manually verified on `2026-09-25` as having four ports and restricted internal access for Audi vehicles. Its `access` and `notes` fields prevent it from being recommended as a public charging stop.

## Vehicles (legacy backend demo fixtures)

- VinFast VF 5 product FAQ: <https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/cau-hoi-xe-o-to/san-pham/vf-5>
- VinFast VF 5 specification article: <https://vinfastauto.com/vn_vi/VF-5-Plus-di-duoc-bao-nhieu-km-sau-1-lan-sac-day>
- VinFast VF 7 official brochure: <https://shop.vinfastauto.com/on/demandware.static/-/Sites-app_vinfast_vn-Library/default/dw8e23886a/Document/VF7_Brochure_25.10.pdf>
- VinFast charging-standard description: <https://vinfastauto.com/vn_vi/uu-diem-xe-vinfast-vf-9>

Nominal capacity is not separately published in the selected sources, so the usable capacity is copied into `battery_capacity_kwh` and declared synthetic. Reserve SOC, target SOC and charging efficiency are project assumptions. `EV_GBT_CITY_DEMO` is a fully synthetic negative compatibility fixture. These three profiles now live in `data_platform/data/demo/vehicles.json`; the separate `data_platform/data/static/vehicles.json` contains 20 DB-oriented profiles with per-field provenance.

For the 2024 BYD ATTO 3 Dynamic and Premium, the [official Vietnam brochure](https://www.byd.com/material/byd-site/vn/proudct-specs/new-catalogue-2024/Brochure_Catalogue_ATTO3_VN_view.pdf) publishes battery capacities of 49.92 and 60.48 kWh and NEDC ranges of 410 and 480 km. Catalog consumption is calculated as published capacity / NEDC range; this is a cycle estimate, not measured real-world consumption. Usable capacity and maximum AC acceptance are not specified and remain unknown. Shared reserve SOC, target SOC and charging efficiency are synthetic planning defaults, not manufacturer specifications.

When a listed connector has no published vehicle charging limit, the demo uses a labeled planning fallback of 3.3 kW AC or 50 kW DC. The `max_ac_kw`/`max_dc_kw` columns remain null; the fallback is stored only in provenance for calculations. VinFast's [VF 9 FAQ](https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/cau-hoi-xe-o-to/san-pham/vf-9) explicitly leaves maximum DC power pending.
