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
    print("演示用户 alice/bob/admin，密码 tutorial123；出行日期", day)


if __name__ == "__main__":
    seed()