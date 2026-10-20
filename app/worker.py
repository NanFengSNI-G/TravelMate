import logging
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from app.checkpoints import MySQLCheckpointSaver
from langgraph.types import Command
from app.config import settings
from app.graph import build_graph
from app.domain import Domain
from app.knowledge import Knowledge
from app.runs import Runs
from app.activity import NODE_LABELS

log = logging.getLogger("worker")


@contextmanager
def checkpoint():
    with MySQLCheckpointSaver.from_conn_string(settings().checkpoint_url) as saver:
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
    for part in graph.stream(
        input_data, cfg, stream_mode="updates", subgraphs=True, version="v2"
    ):
        namespace, event = part["ns"], part["data"]
        if namespace:
            if len(namespace) != 1 or namespace[0].split(":")[0] not in (
                "planning",
                "policy",
                "repair",
            ):
                continue
            event = {
                name: value for name, value in event.items() if name in NODE_LABELS
            }
            if not event:
                continue
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


def consume():
    while True:
        try:
            if not work_once():
                time.sleep(1)
        except Exception:
            log.exception("任务领取暂时失败，稍后重试")
            time.sleep(1)


if __name__ == "__main__":
    settings().dashscope_api_key
    logging.basicConfig(level=logging.INFO)
    with ThreadPoolExecutor(max_workers=settings().worker_concurrency) as pool:
        consumers = [pool.submit(consume) for _ in range(settings().worker_concurrency)]
        for consumer in consumers:
            consumer.result()
