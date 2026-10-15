import logging
import threading
import time
from contextlib import contextmanager
from app.checkpoints import TutorialMySQLSaver
from langgraph.types import Command
from app.config import settings
from app.graph import build_graph
from app.domain import Domain
from app.knowledge import Knowledge
from app.runs import Runs

log = logging.getLogger("worker")


@contextmanager
def checkpoint():
    with TutorialMySQLSaver.from_conn_string(settings().checkpoint_url) as saver:
        saver.setup()
        yield saver


def process(r, graph, runs):
    cfg = {"configurable": {"thread_id": r.id}, "recursion_limit": 60}
    snapshot = graph.get_state(cfg)
    if snapshot.values:
        input_data = (
            Command(resume=r.resume)
            if r.resume and snapshot.tasks and any(t.interrupts for t in snapshot.tasks)
            else None
        )
        # fence 是运行上下文的最新事实，需要在恢复前覆盖旧值。
        graph.update_state(cfg, {"fence": r.fence})
    else:
        input_data = {
            "owner": r.owner,
            "conversation_id": r.conversation,
            "run_id": r.id,
            "fence": r.fence,
            "request": r.payload,
            "results": {},
        }
    for event in graph.stream(input_data, cfg, stream_mode="updates"):
        runs.event(r.id, r.fence, "progress", event)
        if runs.get(r.owner, r.id).cancel_requested:
            result = {
                "message": "已停止后续任务，已完成订单仍有效",
                "operations": runs.completed_operations(r.id),
            }
            runs.complete(r.id, r.fence, "CANCELLED", result)
            return
    state = graph.get_state(cfg)
    interruptions = [i for t in state.tasks for i in t.interrupts]
    if interruptions:
        result = {"approval": interruptions[0].value}
        runs.event(r.id, r.fence, "approval", result)
        runs.complete(r.id, r.fence, "WAITING", result)
    else:
        result = state.values.get("outcome", {})
        runs.event(r.id, r.fence, "result", result)
        runs.complete(r.id, r.fence, "DONE", result)


def work_once():
    runs = Runs()
    r = runs.claim()
    if not r:
        return False
    stop = threading.Event()

    def beat():
        while not stop.wait(20):
            if not runs.heartbeat(r.id, r.fence):
                return

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        with checkpoint() as saver:
            process(r, build_graph(Domain(Knowledge()), saver), runs)
    except Exception as exc:
        log.exception("run failed: %s", r.id)
        runs.complete(r.id, r.fence, "FAILED", {}, str(exc))
    finally:
        stop.set()
        thread.join(timeout=1)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        if not work_once():
            time.sleep(1)
