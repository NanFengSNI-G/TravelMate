from collections import deque
from datetime import timedelta
import json
from pathlib import Path
import re

from sqlalchemy import select, func, text
from app.db import engine, sessions
from app.demo_data import CITIES, resources, append_demo, write_sql_seed, business_today
from app.domain import Domain
from app.models import Resource, Inventory
from app.contracts import Request


def test_city_guides_cover_the_catalog():
    policies = json.loads(Path("data/policies.json").read_text())
    guides = {p["product"] for p in policies if p["supplier"] == "目的地指南"}
    assert len(CITIES) == 20 and len({c["code"] for c in CITIES}) == 20
    assert {c["name"] for c in CITIES} <= guides
    assert all((Path("data") / p["file"]).is_file() for p in policies)


def test_sql_and_python_catalog_preserve_existing_data(db_env, tmp_path):
    path = tmp_path / "demo.sql"
    path.write_text("")
    write_sql_seed(path)
    sql = path.read_text()
    for model in (Resource, Inventory):
        sql = re.sub(
            r"\b" + model.__tablename__.removeprefix(db_env) + r"\b",
            model.__table__.name,
            sql,
        )
    with engine().begin() as connection:
        connection.execute(text("SET time_zone = '+08:00'"))
        for statement in sql.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    start = business_today() + timedelta(days=1)
    rows = resources(start)
    first = next(rows)
    samples = [first, *deque(rows, maxlen=2)]
    with sessions().begin() as session:
        assert session.scalar(select(func.count()).select_from(Resource)) == 46004
        assert session.scalar(select(func.count()).select_from(Inventory)) == 81634
        for expected in samples:
            actual = session.get(Resource, expected["id"])
            assert actual.price == expected["price"]
            assert actual.details == expected["details"]
            assert actual.name == expected["name"]
        session.get(Inventory, first["id"]).available = 7
        session.get(Resource, first["id"]).price += 100
        session.get(Resource, first["id"]).version = 2
    append_demo(start=start)
    with sessions()() as session:
        assert session.get(Inventory, first["id"]).available == 7
        assert session.get(Resource, first["id"]).price == first["price"] + 100
        assert session.get(Resource, first["id"]).version == 2
        assert session.scalar(select(func.count()).select_from(Resource)) == 46004
    req = Request(
        intent="search",
        departure="北京",
        destination="上海",
        start=start,
        end=start + timedelta(days=3),
    )
    domain = Domain(None)
    assert len(domain.search("flight", req)) == 2
    assert len(domain.search("hotel", req)) == 20
    assert len(domain.catalog_summary()["cities"]) == 20
    assert len(domain.policy_choices()) == 3
