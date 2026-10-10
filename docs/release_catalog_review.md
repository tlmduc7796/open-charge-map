# Release catalog candidate review

**Purpose:** prepare a source-backed operator review of the snapshot from
`origin/codex/open-charge-map-main` before any release catalog import.

**Decision:** preview only. No catalog records have been applied. Empty
`synthetic_fields` is a screening result, not operator approval or proof that a
provider's inventory is still current.

## Station candidates

These seven of the 16 source stations have an empty `synthetic_fields` array in
`data_platform/data/static/stations.geojson`. They identify
`goong_places+google_maps+evcs` as the source and carry a project
`source_updated_at` of 2026-09-27. A public listing comparison found four
snapshot matches, two identity/address or inventory conflicts, and one
unresolved access/identity case. This is a read-only desk review; public pages
do not establish live availability or operator authorization. Do not import any
record until the operator approves it.

| Station | Catalog snapshot | Public source check | Review disposition |
| --- | --- | --- | --- |
| `ST_VF_LANDMARK_81` | 208 Tr?n Tr?ng Kim; 8 ports: CCS2 2?60, 2?30 kW; Type2 4?11 kW | [EVCS HCM0031](https://evcs.vn/tram-sac-vinfast-vinhomes-landmark-81-ham-c.hcm0031.html) lists 208 Nguy?n H?u C?nh and the same 8 power/count groups. | **Hold:** address conflict. Confirm station identity and canonical address with the operator. |
| `ST_VF_HUYEN_TRAN_CONG_CHUA` | Provider ID `hcm0653`; 4?CCS2 120 kW (4 ports) | The same-name [EVCS HCM1316 listing](https://evcs.vn/tram-sac-vinfast-bai-do-xe-huyen-tran-cong-chua-c.hcm1316.html) lists 6?120 kW + 6?7 kW (12 ports). | **Hold:** provider ID and inventory conflict. Do not merge HCM1316 into HCM0653 without operator confirmation. |
| `ST_VF_FGW_Q7` | 3?5 ???ng s? 81; 32 ports: CCS2 12?120, 8?60; Type2 12?7 kW | [EVCS HCM1345](https://evcs.vn/tram-sac-vinfast-tram-sac-fgw-c.hcm1345.html) lists the same location and inventory. | Snapshot match; still requires operator approval and dated source confirmation. |
| `ST_VF_VINCOM_DONG_KHOI` | B5?B6 combined; 73 ports: CCS2 2?80, 38?60, 11?30, 16?20; Type2 6?3.5 kW | [EVCS B6 HCM0160](https://evcs.vn/tram-sac-vinfast-vincom-center-dong-khoi-c.hcm0160.html) and [B5 HCM0030](https://evcs.vn/tram-sac-vinfast-vincom-center-dong-khoi-ham-b5-c.hcm0030.html) sum to the same groups and 73 ports. | Snapshot match across two provider records; operator must approve the combined site identity and access. |
| `ST_VF_QL13_BINH_THANH` | 55 Qu?c l? 13; 30 ports: CCS2 4?120, 26?60 kW; catalog access=`public` | The name says ?private parking?; no exact matching provider record was confirmed in this review. | **Hold:** unresolved site identity and public-access claim. |
| `ST_VF_VINCOM_CONG_HOA` | 15?17 C?ng H?a; 29 ports: CCS2 1?250, 28?60 kW | [TheGioiPhuongTien listing](https://thegioiphuongtien.vn/tram-sac-xe-dien/hcm-vincom-plaza-cong-hoa.html) reports the same address and inventory. | Snapshot match against a secondary listing; operator approval and primary source still required. |
| `ST_VF_LA_VELA` | 280 Nam K? Kh?i Ngh?a; 2?CCS2 150 kW | [EVCS HCM0462](https://evcs.vn/tram-sac-vinfast-bai-do-xe-la-vela-saigon-hotel-c.hcm0462.html) reports the same site and inventory. | Snapshot match; operator must confirm hotel access conditions. |

Connector totals match the listed port totals in all seven catalog records. The
four snapshot matches are not operational approvals. The three held records
need their address, identity, inventory, or access claim resolved before import.
A public listing or map pin does not establish that customers can enter a
parking facility or use every listed port.

## Vehicle catalog review

`data_platform/data/static/vehicles.json` contains 20 source profiles and marks
the catalog `catalog_complete: false`. The retrieval snapshot is dated
2026-10-06. Battery values have `observed` provenance; consumption values are
derived from published test-cycle range and are `inferred`, so they are not
real-world consumption measurements. Connectors are `inferred` for 17 of 20
profiles. Five profiles do not have a published AC charging limit and two do
not have a published DC limit.

| Profile | Battery kWh | Consumption kWh/100 km | AC kW | DC kW | Catalog limitation |
| --- | ---: | ---: | ---: | ---: | --- |
| VinFast VF 5 Plus | 37.23 | 11.420 | 6.6 | 50 | Consumption and connector type inferred. |
| VinFast VF 6 Eco | 59.60 | 12.289 | 7.2 | 100 | Consumption and connector type inferred. |
| VinFast VF 6 Plus | 59.60 | 12.957 | 7.2 | 100 | Consumption and connector type inferred. |
| VinFast VF 7 Eco | 59.60 | 13.545 | 7.2 | 100 | Consumption and connector type inferred. |
| VinFast VF 7 Plus FWD | 70.00 | 13.986 | 7.2 | 110 | Consumption and connector type inferred. |
| VinFast VF 7 Plus AWD | 70.00 | 14.925 | 7.2 | 110 | Consumption and connector type inferred. |
| VinFast VF 8 Eco | 87.70 | 13.811 | 11 | 149 | Consumption and connector type inferred. |
| VinFast VF 8 Plus | 87.70 | 18.463 | 11 | 149 | Consumption and connector type inferred. |
| VinFast VF 9 Eco CATL | 123.00 | 19.649 | 11 | — | Maximum DC power unpublished. |
| VinFast VF 9 Plus CATL | 123.00 | 20.432 | 11 | — | Maximum DC power unpublished. |
| VinFast VF 3 Eco | 18.64 | 8.670 | — | 24 | Maximum AC power unpublished. |
| VinFast VF 3 Plus | 18.64 | 8.670 | — | 24 | Maximum AC power unpublished. |
| VinFast Minio Green | 18.30 | 8.714 | 3.3 | 24 | Consumption and connector type inferred. |
| VinFast Herio Green | 37.23 | 11.420 | 6.6 | 50 | Consumption and connector type inferred. |
| VinFast Nerio Green | 41.90 | 13.151 | 6.6 | 60 | Consumption and connector type inferred. |
| VinFast Limo Green | 60.13 | 13.362 | 6.9 | 80 | Consumption and connector type inferred. |
| VinFast EC Van | 18.23 | 10.417 | — | 24.2 | Maximum AC power unpublished; CCS2 only in this record. |
| VinFast VF MPV 7 | 60.13 | 13.362 | 6.9 | 80 | Consumption and connector type inferred. |
| BYD ATTO 3 Dynamic 2024 | 49.92 | 12.176 | — | 70 | Maximum AC and usable capacity unpublished; consumption inferred. |
| BYD ATTO 3 Premium 2024 | 60.48 | 12.600 | — | 70 | Maximum AC and usable capacity unpublished; consumption inferred. |

The shared calculation defaults are explicitly synthetic: reserve SOC `0.1`,
target SOC `0.8`, charging efficiency `0.9`, and planning fallbacks of 3.3 kW
AC / 50 kW DC. They must not be treated as manufacturer specifications or
loaded as release vehicle facts without an approved product policy.

## Before import

1. Have the station operator confirm or reject each candidate and resolve the
   Quốc lộ 13 access conflict.
2. Confirm the connector and power groups from provider records, including
   source URLs or dated export artifacts.
3. Approve vehicle compatibility provenance and a planning policy for reserve
   SOC, target SOC, efficiency, missing usable capacity, and unpublished charge
   limits. The release importer now requires `field_provenance` for every
   vehicle input field, preserves `observed`/`inferred` origins, and requires
   policy IDs for the three calculation defaults; the current source bundle
   still needs to be transformed and reviewed to provide those entries.
4. Transform the approved records to the backend `StationCollection` and
   `Vehicle[]` contracts. If the operator supplies stable port IDs, prepare a
   reviewed station-ID/port-label mapping JSON and pass it with `--port-map`.
   Run `import_release_catalog.py` in preview mode; preview must report zero
   synthetic eligibility issues before an operator records approval and applies
   the import.

Source references and collection notes are in
[`data_platform/data/static/SOURCES.md`](../data_platform/data/static/SOURCES.md).
This review contains no credentials and performs no database writes.
