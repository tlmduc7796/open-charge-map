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

The Audi Ho Chi Minh station was manually verified on `2026-09-25` as having four ports and restricted internal access for Audi vehicles. Its `access` and `notes` fields prevent it from being recommended as a public charging stop.

## Vehicles

- VinFast VF 5 product FAQ: <https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/cau-hoi-xe-o-to/san-pham/vf-5>
- VinFast VF 5 specification article: <https://vinfastauto.com/vn_vi/VF-5-Plus-di-duoc-bao-nhieu-km-sau-1-lan-sac-day>
- VinFast VF 7 official brochure: <https://shop.vinfastauto.com/on/demandware.static/-/Sites-app_vinfast_vn-Library/default/dw8e23886a/Document/VF7_Brochure_25.10.pdf>
- VinFast charging-standard description: <https://vinfastauto.com/vn_vi/uu-diem-xe-vinfast-vf-9>

Nominal capacity is not separately published in the selected sources, so the usable capacity is copied into `battery_capacity_kwh` and declared synthetic. Reserve SOC, target SOC and charging efficiency are project assumptions. `EV_GBT_CITY_DEMO` is a fully synthetic negative compatibility fixture.
