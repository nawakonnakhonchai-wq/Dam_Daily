import json
import pandas as pd
import requests

# 1. ดึงข้อมูลปริมาณน้ำรายวันจากกรมชลประทาน
url_api_dam = 'https://app.rid.go.th/reservoir/api/dam/public'
res_dam = requests.get(url_api_dam)

dams_list = []
api_date = ''
if res_dam.status_code == 200:
  api_data = res_dam.json()
  api_date = api_data.get('date', '')
  for region_group in api_data.get('data', []):
    region_name = region_group.get('region')
    for dam in region_group.get('dam', []):
      dam['region'] = region_name
      dams_list.append(dam)

df_api = pd.DataFrame(dams_list)

# 2. ดึงข้อมูลพิกัดและโครงสร้าง GeoJSON จาก IEAT API
url_gis = 'https://emonitor.ieat.go.th/call_feed/geog/GeoData/rid_conv_gis.json'
res_gis = requests.get(url_gis)

gis_features = []
if res_gis.status_code == 200:
  gis_data = res_gis.json()
  gis_features = gis_data.get('features', [])

# แปลงข้อมูลพิกัดจาก IEAT ให้เป็น DataFrame เพื่อง่ายต่อการ Join
gis_rows = []
for feat in gis_features:
  props = feat.get('properties', {})
  geom = feat.get('geometry', {})
  coords = geom.get('coordinates', [None, None]) if geom else [None, None]

  gis_rows.append({
      'name': props.get('name') or props.get('DAM_NAME'),  # ปรับ Key ตามโครงสร้างจริงของ JSON ฝั่ง IEAT
      'longitude': coords[0],
      'latitude': coords[1],
      'original_properties': props,
  })

df_gis = pd.DataFrame(gis_rows)

# 3. รวมข้อมูล (Merge) ระหว่างข้อมูลน้ำจากกรมชลประทาน กับ พิกัดจาก IEAT (ใช้ชื่อเขื่อน 'name' เป็น Key)
# ใช้แบบ Left Join เพื่อรักษาข้อมูลเขื่อนทั้งหมดจากกรมชลประทานเอาไว้
if not df_api.empty and not df_gis.empty:
  df_merged = pd.merge(df_api, df_gis, on='name', how='left')
else:
  df_merged = df_api

# 4. สร้างโครงสร้าง GeoJSON ใหม่ที่อัปเดตข้อมูลน้ำล่าสุด
final_features = []
for _, row in df_merged.iterrows():
  # ตรวจสอบว่ามีพิกัดหรือไม่
  lat = row.get('latitude')
  lon = row.get('longitude')

  if pd.notna(lat) and pd.notna(lon):
    geometry = {'type': 'Point', 'coordinates': [float(lon), float(lat)]}
  else:
    geometry = None  # กรณีไม่มีพิกัดในระบบ IEAT

  feature = {
      'type': 'Feature',
      'geometry': geometry,
      'properties': {
          'id': row.get('id'),
          'name': row.get('name'),
          'region': row.get('region'),
          'capacity': row.get('capacity'),
          'volume': row.get('volume'),
          'percent_storage': row.get('percent_storage'),
          'inflow': row.get('inflow'),
          'outflow': row.get('outflow'),
          'date': api_date,
      },
  }
  final_features.append(feature)

geojson_output = {'type': 'FeatureCollection', 'features': final_features}

# 5. บันทึกไฟล์ GeoJSON ออกมา
output_filename = 'rid_dams_updated.geojson'
with open(output_filename, 'w', encoding='utf-8') as f:
  json.dump(geojson_output, f, ensure_ascii=False, indent=4)

print(
    f'สร้างไฟล์ {output_filename} สำเร็จ! (รวมทั้งหมด {len(final_features)}'
    ' แห่ง)'
)
