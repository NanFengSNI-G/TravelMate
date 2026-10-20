import json
from datetime import datetime, timedelta
from itertools import islice
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.mysql import insert
from app.db import sessions
from app.models import Resource, Inventory

CITIES = json.loads(
    (Path(__file__).resolve().parents[1] / "data/cities.json").read_text()
)
FLIGHT_DAYS = 60
HOTEL_DAYS = 90
HOTELS_PER_CITY = 10


def business_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def resources(start, days=FLIGHT_DAYS):
    for a, origin in enumerate(CITIES):
        for b, city in enumerate(CITIES):
            if a == b:
                continue
            for offset in range(days):
                day = start + timedelta(days=offset)
                for slot in range(2):
                    yield dict(
                        id=f'demo-flight-{origin["code"]}-{city["code"]}-{day:%Y%m%d}-{slot}',
                        kind="flight",
                        name=f'演示航空 TM{a * 40 + b * 2 + slot + 1000} {origin["name"]}→{city["name"]}',
                        supplier="演示航空",
                        product="economy",
                        version=1,
                        price=25000
                        + ((a * 173 + b * 97) % 900) * 100
                        + slot * 13000
                        + day.weekday() * 1500,
                        details=dict(
                            departure=origin["name"],
                            destination=city["name"],
                            date=str(day),
                            departure_time="08:20" if slot == 0 else "17:50",
                            cabin="经济舱",
                            demo=True,
                        ),
                    )
    for c, city in enumerate(CITIES):
        for hotel in range(HOTELS_PER_CITY):
            for room in range(2):
                product = "standard" if room == 0 else "flexible"
                room_name = "标准双床房" if room == 0 else "灵活大床房"
                yield dict(
                    id=f'demo-hotel-{city["code"]}-{hotel:02}-{product}',
                    kind="hotel",
                    name=f'{city["name"]}·云旅{hotel + 1:02}酒店（{city["area"]}店）·{room_name}',
                    supplier="演示酒店",
                    product=product,
                    version=1,
                    price=18000 + c % 5 * 3000 + hotel * 4500 + room * 6000,
                    details=dict(
                        destination=city["name"],
                        district=city["area"],
                        max_people=2,
                        room_type=room_name,
                        breakfast=hotel % 2 == 0,
                        demo=True,
                    ),
                )


def inventories(start, days=FLIGHT_DAYS):
    for r in resources(start, days):
        if r["kind"] == "flight":
            yield dict(
                id=r["id"], resource=r["id"], day=r["details"]["date"], available=60
            )
        else:
            for offset in range(max(HOTEL_DAYS, days + 14)):
                day = str(start + timedelta(days=offset))
                yield dict(
                    id=f'{r["id"]}-{day}', resource=r["id"], day=day, available=12
                )


def append_demo(days=FLIGHT_DAYS, start=None):
    if not 1 <= days <= 365:
        raise ValueError("航班天数必须为 1—365")
    start = start or business_today() + timedelta(days=1)
    counts = {}
    with sessions().begin() as session:
        for model, rows in [
            (Resource, resources(start, days)),
            (Inventory, inventories(start, days)),
        ]:
            iterator = iter(rows)
            added = 0
            while batch := list(islice(iterator, 1000)):
                statement = insert(model.__table__).values(batch)
                result = session.execute(
                    statement.on_duplicate_key_update(id=model.__table__.c.id)
                )
                added += result.rowcount
            counts[model.__tablename__] = added
    return dict(
        start=str(start), end=str(start + timedelta(days=days - 1)), processed=counts
    )


def write_sql_seed(path=Path("travelmate.sql")):
    cities = json.dumps(CITIES, ensure_ascii=False).replace("'", "''")
    days = ",".join(f"({i})" for i in range(HOTEL_DAYS))
    city_table = "JSON_TABLE(@demo_cities, '$[*]' COLUMNS (n FOR ORDINALITY, code VARCHAR(8) PATH '$.code', city VARCHAR(40) PATH '$.name', area VARCHAR(40) PATH '$.area'))"
    sql = f"""
-- demo-catalog
SET @demo_start = DATE_ADD(CURDATE(), INTERVAL 1 DAY);
SET @demo_cities = '{cities}';
CREATE TEMPORARY TABLE _demo_days (n INT PRIMARY KEY);
INSERT INTO _demo_days VALUES {days};
START TRANSACTION;
INSERT IGNORE INTO resources (id,kind,name,supplier,product,details,price,version)
SELECT CONCAT('demo-flight-',a.code,'-',b.code,'-',DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y%m%d'),'-',s.v),
 'flight',CONCAT('演示航空 TM', (a.n-1)*40+(b.n-1)*2+s.v+1000,' ',a.city,'→',b.city),'演示航空','economy',
 JSON_OBJECT('departure',a.city,'destination',b.city,'date',DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y-%m-%d'),
 'departure_time',IF(s.v=0,'08:20','17:50'),'cabin','经济舱','demo',CAST('true' AS JSON)),
 25000+MOD((a.n-1)*173+(b.n-1)*97,900)*100+s.v*13000+WEEKDAY(DATE_ADD(@demo_start,INTERVAL d.n DAY))*1500,1
FROM {city_table} a CROSS JOIN {city_table} b CROSS JOIN _demo_days d CROSS JOIN (SELECT 0 v UNION ALL SELECT 1) s
WHERE a.n<>b.n AND d.n<{FLIGHT_DAYS};
INSERT IGNORE INTO resources (id,kind,name,supplier,product,details,price,version)
SELECT CONCAT('demo-hotel-',a.code,'-',LPAD(h.n,2,'0'),'-',IF(s.v=0,'standard','flexible')),
 'hotel',CONCAT(a.city,'·云旅',LPAD(h.n+1,2,'0'),'酒店（',a.area,'店）·',IF(s.v=0,'标准双床房','灵活大床房')),
 '演示酒店',IF(s.v=0,'standard','flexible'),
 JSON_OBJECT('destination',a.city,'district',a.area,'max_people',2,'room_type',IF(s.v=0,'标准双床房','灵活大床房'),
 'breakfast',CAST(IF(MOD(h.n,2)=0,'true','false') AS JSON),'demo',CAST('true' AS JSON)),
 18000+MOD(a.n-1,5)*3000+h.n*4500+s.v*6000,1
FROM {city_table} a CROSS JOIN _demo_days h CROSS JOIN (SELECT 0 v UNION ALL SELECT 1) s WHERE h.n<{HOTELS_PER_CITY};
INSERT IGNORE INTO inventory (id,resource,day,available)
SELECT id,id,JSON_UNQUOTE(JSON_EXTRACT(details,'$.date')),60 FROM resources WHERE id LIKE 'demo-flight-%';
INSERT IGNORE INTO inventory (id,resource,day,available)
SELECT CONCAT(r.id,'-',DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y-%m-%d')),r.id,
 DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y-%m-%d'),12
FROM resources r CROSS JOIN _demo_days d WHERE r.id LIKE 'demo-hotel-%';
COMMIT;
DROP TEMPORARY TABLE _demo_days;
"""
    path.write_text(path.read_text().split("-- demo-catalog")[0].rstrip() + "\n" + sql)
