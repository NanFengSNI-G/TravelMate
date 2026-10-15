import os
import pytest
from app.checkpoints import TutorialMySQLSaver
from app.graph import build_graph
from app.domain import Domain
from app.runs import Runs
from app.worker import process
from tests.test_graph import conversation
from tests.test_domain import req


@pytest.mark.integration
def test_mysql_checkpoint_new_connection_resume(env):
    from app.config import settings

    url = settings().checkpoint_url
    runs = Runs()
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    with TutorialMySQLSaver.from_conn_string(url) as saver:
        saver.setup()
        process(runs.claim(), build_graph(Domain(env), saver), runs)
    assert runs.get("alice", rid).status == "WAITING"
    runs.resume("alice", rid, {"decision": "approve", "version": 1})
    # 关闭旧连接，用全新的 saver 和图模拟进程重启。
    with TutorialMySQLSaver.from_conn_string(url) as saver:
        process(runs.claim(), build_graph(Domain(env), saver), runs)
    assert runs.get("alice", rid).status == "DONE"
    assert len(Domain(env).orders("alice")) == 2
