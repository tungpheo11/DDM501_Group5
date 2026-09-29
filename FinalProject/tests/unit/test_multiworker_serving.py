"""Multi-worker serving: Prometheus multiprocess exposition, process-tree metrics,
model generation sync between workers and the gunicorn hooks."""

import importlib
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from credit_risk.config import load_settings
from credit_risk.monitoring import metrics
from credit_risk.monitoring.multiprocess import (
    ProcessTreeCollector,
    build_multiprocess_registry,
    mark_worker_dead,
    reset_multiprocess_dir,
)
from credit_risk.serving.model_loader import ModelManager
from credit_risk.serving.model_sync import MARKER_FILE, ModelGenerationSync, ModelSyncWatcher

SRC = Path(__file__).resolve().parents[2] / "src"


def _worker(mp_dir: Path, code: str) -> int:
    """Run ``code`` in a fresh interpreter acting as one API worker; return its pid."""
    script = "import os\nfrom credit_risk.monitoring import metrics as m\n" + textwrap.dedent(code)
    script += "\nprint(os.getpid())\n"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "PROMETHEUS_MULTIPROC_DIR": str(mp_dir),
        "PYTHONPATH": os.pathsep.join(filter(None, [str(SRC), os.environ.get("PYTHONPATH")])),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120, check=True
    )
    return int(completed.stdout.strip().splitlines()[-1])


def _samples(mp_dir: Path, name: str) -> list[tuple[dict[str, str], float]]:
    text = generate_latest(build_multiprocess_registry(mp_dir, root_pid=os.getpid())).decode()
    return [
        (sample.labels, sample.value)
        for family in text_string_to_metric_families(text)
        for sample in family.samples
        if sample.name == name
    ]


@pytest.fixture
def mp_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "metrics"
    reset_multiprocess_dir(directory)
    return directory


# --- Prometheus multiprocess registry ------------------------------------------------


def test_counters_and_histograms_are_summed_across_workers(mp_dir):
    for count, batch in ((3, 10), (4, 5)):
        _worker(
            mp_dir,
            f"m.PREDICTION_REQUESTS.labels(decision='APPROVE', status='200').inc({count})\n"
            f"m.BATCH_SIZE_HISTOGRAM.observe({batch})",
        )
    assert _samples(mp_dir, "credit_prediction_requests_total") == [({"decision": "APPROVE", "status": "200"}, 7.0)]
    assert _samples(mp_dir, "credit_prediction_batch_size_count") == [({}, 2.0)]


def test_model_info_exposes_only_the_served_identity(mp_dir):
    _worker(
        mp_dir,
        """
        m.set_served_model("credit-risk-model", "5", "mlflow_registry", degraded=False)
        m.set_served_model("credit-risk-model", "6", "mlflow_registry", degraded=False)
        """,
    )
    _worker(mp_dir, 'm.set_served_model("credit-risk-model", "6", "mlflow_registry", degraded=False)')
    info = _samples(mp_dir, "credit_model_info")
    assert info == [({"model_name": "credit-risk-model", "model_version": "6", "source": "mlflow_registry"}, 1.0)]
    assert _samples(mp_dir, "credit_model_loaded") == [({}, 1.0)]


def test_model_gauges_combine_workers_and_forget_dead_ones(mp_dir):
    _worker(mp_dir, 'm.set_served_model("credit-risk-model", "6", "mlflow_registry", degraded=False)')
    unavailable = _worker(mp_dir, "m.set_model_unavailable()")
    # livemin / livemax: one worker without a model is enough to report it.
    assert _samples(mp_dir, "credit_model_loaded") == [({}, 0.0)]
    assert _samples(mp_dir, "credit_model_degraded") == [({}, 1.0)]

    mark_worker_dead(unavailable, mp_dir)
    assert _samples(mp_dir, "credit_model_loaded") == [({}, 1.0)]
    assert _samples(mp_dir, "credit_model_degraded") == [({}, 0.0)]
    assert len(_samples(mp_dir, "credit_model_info")) == 1


def test_counters_of_dead_workers_are_kept(mp_dir):
    dead = _worker(mp_dir, "m.MODEL_RELOADS.labels(result='success').inc()")
    _worker(mp_dir, "m.MODEL_RELOADS.labels(result='success').inc()")
    mark_worker_dead(dead, mp_dir)
    assert _samples(mp_dir, "credit_model_reloads_total") == [({"result": "success"}, 2.0)]


def test_rolling_gauges_report_the_most_recent_worker(mp_dir):
    _worker(mp_dir, "m.DEFAULT_RISK_RATIO.set(0.2)")
    _worker(mp_dir, "import time\ntime.sleep(0.05)\nm.DEFAULT_RISK_RATIO.set(0.7)")
    assert _samples(mp_dir, "credit_default_prediction_ratio") == [({}, 0.7)]


def test_gauge_multiprocess_modes():
    assert metrics.MODEL_LOADED._multiprocess_mode == "livemin"
    assert metrics.MODEL_DEGRADED._multiprocess_mode == "livemax"
    assert metrics.MODEL_INFO._multiprocess_mode == "livemax"
    for gauge in (
        metrics.DEFAULT_RISK_RATIO,
        metrics.AVG_AGE_GAUGE,
        metrics.AVG_LIMIT_GAUGE,
        metrics.AVG_UTILIZATION_GAUGE,
        metrics.PAY_0_DELAY_RATIO,
    ):
        assert gauge._multiprocess_mode == "livemostrecent"


def test_single_process_mode_drops_the_previous_identity():
    metrics.set_served_model("credit-risk-model", "5", "mlflow_registry", degraded=False)
    metrics.set_served_model("credit-risk-model", "6", "mlflow_registry", degraded=True)
    text = generate_latest(REGISTRY).decode()
    assert 'model_version="6"' in text
    assert 'model_version="5"' not in text
    metrics.set_model_unavailable()
    assert "credit_model_info{" not in generate_latest(REGISTRY).decode()


def test_metrics_endpoint_serves_the_multiprocess_registry(mp_dir, monkeypatch, make_client):
    _worker(mp_dir, "m.AUTH_FAILURES.labels(reason='other-worker').inc(5)")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(mp_dir))
    body = make_client().get("/metrics").text
    assert 'credit_api_auth_failures_total{reason="other-worker"} 5.0' in body


# --- Process tree collector ------------------------------------------------------------


def _write_stat(proc: Path, pid: int, ppid: int, utime: int, stime: int, rss: int, cutime: int = 0, cstime: int = 0):
    fields = ["S", str(ppid)] + ["0"] * 9 + [str(utime), str(stime), str(cutime), str(cstime)] + ["0"] * 6
    fields += [str(rss)] + ["0"] * 10
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "stat").write_text(f"{pid} (gunicorn: worker [app]) " + " ".join(fields) + "\n")


def _collect(collector: ProcessTreeCollector) -> dict[str, float]:
    return {family.name: family.samples[0].value for family in collector.collect()}


def test_process_tree_collector_sums_master_and_workers(tmp_path):
    proc = tmp_path / "proc"
    _write_stat(proc, 100, 1, utime=100, stime=50, rss=1000, cutime=30, cstime=20)
    _write_stat(proc, 101, 100, utime=200, stime=100, rss=2000)
    _write_stat(proc, 102, 100, utime=10, stime=10, rss=500)
    _write_stat(proc, 200, 1, utime=9999, stime=9999, rss=9999)
    (proc / "self").mkdir()
    collector = ProcessTreeCollector(100, proc_root=proc)
    values = _collect(collector)
    ticks, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    assert values["process_cpu_seconds"] == pytest.approx((100 + 50 + 30 + 20 + 300 + 20) / ticks)
    assert values["process_resident_memory_bytes"] == (1000 + 2000 + 500) * page


def test_process_tree_collector_without_root_process(tmp_path):
    assert _collect(ProcessTreeCollector(4242, proc_root=tmp_path)) == {}


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs Linux /proc")
def test_process_tree_collector_on_real_proc():
    values = _collect(ProcessTreeCollector(os.getpid()))
    assert values["process_cpu_seconds"] > 0
    assert values["process_resident_memory_bytes"] > 0


# --- Model generation marker -----------------------------------------------------------


def test_marker_publish_and_read_roundtrip(tmp_path):
    sync = ModelGenerationSync(tmp_path / "sync")
    assert sync.read() is None
    generation = sync.publish("7")
    assert sync.read() == generation
    assert generation.model_version == "7"
    assert generation.pid == os.getpid()
    assert [path.name for path in (tmp_path / "sync").iterdir()] == [MARKER_FILE]


def test_marker_is_pending_only_for_other_workers(tmp_path):
    publisher, follower = ModelGenerationSync(tmp_path), ModelGenerationSync(tmp_path)
    follower.mark_current_applied()
    generation = publisher.publish("8")
    assert publisher.pending() is None
    assert follower.pending() == generation
    follower.acknowledge(generation, success=True)
    assert follower.pending() is None


def test_failed_apply_backs_off_before_retrying(tmp_path):
    publisher = ModelGenerationSync(tmp_path)
    generation = publisher.publish("8")
    patient, eager = ModelGenerationSync(tmp_path, retry_seconds=60), ModelGenerationSync(tmp_path, retry_seconds=0)
    patient.acknowledge(generation, success=False)
    eager.acknowledge(generation, success=False)
    assert patient.pending() is None
    assert eager.pending() == generation


def test_unreadable_marker_is_ignored(tmp_path):
    (tmp_path / MARKER_FILE).write_text("{not json")
    assert ModelGenerationSync(tmp_path).read() is None


class _FakeManager:
    def __init__(self, success: bool = True):
        self.success = success
        self.calls: list[bool] = []

    def load_champion(self, *, broadcast: bool = False):
        self.calls.append(broadcast)
        return type("Outcome", (), {"success": self.success})()


def test_watcher_reloads_once_per_generation(tmp_path):
    ModelGenerationSync(tmp_path).publish("9")
    manager, reloaded = _FakeManager(), []
    watcher = ModelSyncWatcher(ModelGenerationSync(tmp_path), manager, on_reload=lambda: reloaded.append(1))
    assert watcher.check_once() is True
    assert watcher.check_once() is False
    assert manager.calls == [False]
    assert reloaded == [1]


def test_watcher_retries_a_failed_reload(tmp_path):
    ModelGenerationSync(tmp_path).publish("9")
    manager = _FakeManager(success=False)
    watcher = ModelSyncWatcher(ModelGenerationSync(tmp_path, retry_seconds=0), manager)
    assert watcher.check_once() is True
    manager.success = True
    assert watcher.check_once() is True
    assert watcher.check_once() is False


def test_watcher_thread_follows_a_new_generation(tmp_path):
    follower = ModelGenerationSync(tmp_path)
    follower.mark_current_applied()
    manager = _FakeManager()
    watcher = ModelSyncWatcher(follower, manager, interval_seconds=0.02)
    watcher.start()
    try:
        ModelGenerationSync(tmp_path).publish("10")
        deadline = time.monotonic() + 5
        while not manager.calls and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        watcher.stop()
    assert manager.calls == [False]


def test_only_successful_broadcast_reloads_publish(settings, tmp_path, monkeypatch):
    sync = ModelGenerationSync(tmp_path)
    manager = ModelManager(settings, sync=sync)
    manager.load_champion()
    assert sync.read() is None
    manager.load_champion(broadcast=True)
    published = sync.read()
    assert published is not None
    assert published.model_version == "credit_model_v1"

    monkeypatch.setattr(manager, "_load_from_local", lambda: None)
    assert manager.load_champion(broadcast=True).success is False
    assert sync.read() == published


def test_publish_error_keeps_the_reload_successful(settings, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    manager = ModelManager(settings, sync=ModelGenerationSync(blocker))
    assert manager.load_champion(broadcast=True).success is True


def test_reload_endpoint_publishes_a_generation(make_client, auth_headers, tmp_path):
    client = make_client(model_sync_dir=tmp_path)
    response = client.post("/api/v1/model/reload", headers=auth_headers)
    assert response.status_code == 200
    assert ModelGenerationSync(tmp_path).read().model_version == response.json()["model"]["model_version"]


def test_settings_for_worker_pool_and_sync(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    monkeypatch.setenv("MODEL_SYNC_DIR", str(tmp_path))
    cfg = load_settings(env="test")
    assert (cfg.database.pool_size, cfg.database.max_overflow) == (3, 2)
    assert cfg.serving.model_sync_dir == tmp_path
    monkeypatch.delenv("MODEL_SYNC_DIR")
    assert load_settings(env="test").serving.model_sync_dir is None


# --- gunicorn config -------------------------------------------------------------------


def test_gunicorn_config_does_not_import_prometheus_client():
    script = "import sys, credit_risk.serving.gunicorn_conf as c; print('prometheus_client' in sys.modules, c.workers)"
    env = {**os.environ, "PYTHONPATH": str(SRC), "API_WORKERS": "3"}
    completed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert completed.stdout.split() == ["False", "3"]


def test_gunicorn_config_defaults(monkeypatch):
    monkeypatch.delenv("API_WORKERS", raising=False)
    conf = importlib.reload(importlib.import_module("credit_risk.serving.gunicorn_conf"))
    assert conf.workers == 2
    assert conf.bind == "0.0.0.0:8000"
    assert conf.worker_class == "uvicorn_worker.UvicornWorker"
    assert conf.graceful_timeout == 20
    assert conf.accesslog is None


def test_gunicorn_hooks_prepare_dirs_and_forget_dead_workers(tmp_path, monkeypatch):
    conf = importlib.import_module("credit_risk.serving.gunicorn_conf")
    metrics_dir, sync_dir = tmp_path / "metrics", tmp_path / "sync"
    metrics_dir.mkdir()
    (metrics_dir / "counter_1.db").write_bytes(b"stale")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(metrics_dir))
    monkeypatch.setenv("MODEL_SYNC_DIR", str(sync_dir))
    monkeypatch.setenv("API_MASTER_PID", "0")
    logged = []
    server = type("Server", (), {"log": type("Log", (), {"info": lambda *args: logged.append(args)})()})()

    conf.on_starting(server)
    assert list(metrics_dir.iterdir()) == []
    assert sync_dir.is_dir()
    assert os.environ["API_MASTER_PID"] == str(os.getpid())
    assert logged

    (metrics_dir / "gauge_livemin_4242.db").write_bytes(b"")
    (metrics_dir / "counter_4242.db").write_bytes(b"")
    conf.child_exit(server, type("Worker", (), {"pid": 4242})())
    assert sorted(path.name for path in metrics_dir.iterdir()) == ["counter_4242.db"]
