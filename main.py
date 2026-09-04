import json
import pandas as pd
import requests


def clean_name(name):
  if pd.isna(name):
    return ""
  return (
      str(name)
      .replace("เขื่อน", "")
      .replace("อ่างเก็บน้ำ", "")
      .replace("ขนาดกลาง", "")
      .strip()
  )


# ฟังก์ชันแปลงค่า NaN ให้เป็นค่าที่ ArcGIS Online อ่านแล้วไม่พัง
def safe_value(val, default_type="str"):
  if pd.isna(val) or val is None:
    return 0 if default_type == "num" else ""
  if default_type == "num":
    try:
      return float(val)
    except:
      return 0
  return str(val)


def fetch_rid_data(url):
  res = requests.get(url)
  items = []
  api_date = ""
  if res.status_code == 200:
    data = res.json()
    api_date = data.get("date", "")
    for region_group in data.get("data", []):
      region_name = region_group.get("region")
      sub_items = region_group.get("dam") or region_group.get(
          "reservoir"
      ) or region_group.get("data", [])
      if isinstance(sub_items, list):
        for item in sub_items:
          item["region"] = region_name
          items.append(item)
  return items, api_date


# 1. ดึงข้อมูลเขื่อนขนาดใหญ่
url_large = "https://app.rid.go.th/reservoir/api/dam/public"
large_list, date_large = fetch_rid_data(url_large)

# 2. ดึงข้อมูลอ่างเก็บน้ำขนาดกลาง
url_medium = "https://app.rid.go.th/reservoir/api/reservoir/public"
medium_list, date_medium = fetch_rid_data(url_medium)

all_water_data = large_list + medium_list
df_api = pd.DataFrame(all_water_data)
api_date = date_large if date_large else date_medium

if not df_api.empty:
  df_api["clean_name"] = df_api["name"].apply(clean_name)

# 3. ดึงข้อมูลพิกัดจาก IEAT API
url_gis = "https://emonitor.ieat.go.th/call_feed/geog/GeoData/rid_conv_gis.json"
res_gis = requests.get(url_gis)

gis_rows = []
if res_gis.status_code == 200:
  gis_data = res_gis.json()
  for feat in gis_data.get("features", []):
    props = feat.get("properties", {})
    geom = feat.get("geometry", {})
    coords = geom.get("coordinates", [None, None]) if geom else [None, None]

    raw_name = props.get("name") or props.get("DAM_NAME") or ""
    gis_rows.append({
        "name_gis": raw_name,
        "clean_name": clean_name(raw_name),
        "longitude": coords[0],
        "latitude": coords[1],
        "original_properties": props,
    })

df_gis = pd.DataFrame(gis_rows)

# 4. รวมข้อมูล (Merge)
if not df_api.empty and not df_gis.empty:
  df_merged = pd.merge(df_api, df_gis, on="clean_name", how="left")
else:
  df_merged = df_api

# 5. สร้างโครงสร้าง GeoJSON (จัดการกรอง NaN ตรงนี้)
final_features = []
missing_count = 0

for _, row in df_merged.iterrows():
  lat = row.get("latitude")
  lon = row.get("longitude")

  if pd.notna(lat) and pd.notna(lon):
    geometry = {"type": "Point", "coordinates": [float(lon), float(lat)]}
  else:
    geometry = None
    missing_count += 1

  feature = {
      "type": "Feature",
      "geometry": geometry,
      "properties": {
          "id": safe_value(row.get("id"), "str"),  # รหัส
          "name": safe_value(row.get("name"), "str"),  # ชื่อเขื่อน / อ่างเก็บน้ำ
          "region": safe_value(row.get("region"), "str"),  # ภูมิภาค
          "capacity": safe_value(
              row.get("capacity"), "num"
          ),  # ความจุสูงสุด (ล้าน ลบ.ม.)
          "volume": safe_value(
              row.get("volume"), "num"
          ),  # ปริมาณน้ำปัจจุบัน (ล้าน ลบ.ม.)
          "percent_storage": safe_value(
              row.get("percent_storage"), "num"
          ),  # เปอร์เซ็นต์น้ำเก็บกัก (%)
          "inflow": safe_value(row.get("inflow"), "num"),  # น้ำไหลเข้า
          "outflow": safe_value(row.get("outflow"), "num"),  # น้ำระบายออก
          "date": safe_value(api_date, "str"),  # วันที่ของข้อมูล
      },
  }
  final_features.append(feature)

geojson_output = {"type": "FeatureCollection", "features": final_features}

output_filename = "rid_dams_updated.geojson"
with open(output_filename, "w", encoding="utf-8") as f:
  json.dump(geojson_output, f, ensure_ascii=False, indent=4)

print(f"\n--- สรุปผลการสร้าง GeoJSON ---")
print(f"ข้อมูลน้ำรวมทั้งหมด: {len(final_features)} แห่ง")
print(f"ที่มีพิกัดครบถ้วน: {len(final_features) - missing_count} แห่ง")
print(f"ที่ยังขาดพิกัด: {missing_count} แห่ง")
