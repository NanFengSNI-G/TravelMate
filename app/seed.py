from datetime import date, timedelta
from sqlalchemy import select
from app.db import engine, sessions
from app.models import Base, User, Resource, Inventory
from app.auth import password_hash


def seed():
    Base.metadata.create_all(engine())
    with sessions().begin() as s:
        for name, role in [("alice", "user"), ("bob", "user"), ("admin", "admin")]:
            if not s.scalar(select(User).where(User.name == name)):
                s.add(
                    User(
                        id=name,
                        name=name,
                        password=password_hash("tutorial123"),
                        role=role,
                    )
                )
        day = date.today() + timedelta(days=30)
        for i in range(2):
            rid = f"flight-{i}"
            if not s.get(Resource, rid):
                s.add(
                    Resource(
                        id=rid,
                        kind="flight",
                        name=f"演示航班 {i}",
                        supplier="演示航空",
                        product="economy",
                        price=80000 + i * 20000,
                        details={
                            "departure": "北京",
                            "destination": "上海",
                            "date": str(day + timedelta(days=i)),
                        },
                    )
                )
                s.add(
                    Inventory(
                        id=rid,
                        resource=rid,
                        day=str(day + timedelta(days=i)),
                        available=6,
                    )
                )
            rid = f"hotel-{i}"
            if not s.get(Resource, rid):
                s.add(
                    Resource(
                        id=rid,
                        kind="hotel",
                        name=f"演示酒店 {i}",
                        supplier="演示酒店",
                        product="standard" if i == 0 else "flexible",
                        price=30000 + i * 10000,
                        details={"destination": "上海", "max_people": 2},
                    )
                )
                for n in range(16):
                    d = str(day + timedelta(days=n))
                    s.add(Inventory(id=f"{rid}-{d}", resource=rid, day=d, available=3))
    print("基础演示账号与资源已就绪")


if __name__ == "__main__":
    import argparse
    from app.demo_data import append_demo, write_sql_seed

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--export-sql", action="store_true")
    args = parser.parse_args()
    if args.export_sql:
        write_sql_seed()
    else:
        seed()
        print("扩展示例目录：", append_demo(args.days))
