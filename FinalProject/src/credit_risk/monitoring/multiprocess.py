"""Prometheus exposition when the API runs as several gunicorn worker processes.

Workers write metric values to memory-mapped files in ``PROMETHEUS_MULTIPROC_DIR``;
``/metrics`` (served by any worker) merges them with :class:`MultiProcessCollector`.
The variable must be set before :mod:`prometheus_client` is imported, which the
gunicorn config does in the master before forking. Without it the API keeps the
default single-process registry.

The default process collector would only describe the worker answering the scrape,
so :class:`ProcessTreeCollector` reports ``process_cpu_seconds_total`` and
``process_resident_memory_bytes`` for the gunicorn master plus all its workers.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path

from prometheus_client import CollectorRegistry
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.multiprocess import MultiProcessCollector, mark_process_dead
from prometheus_client.registry import Collector

MULTIPROC_DIR_ENV = "PROMETHEUS_MULTIPROC_DIR"
MASTER_PID_ENV = "API_MASTER_PID"

# Retired identities stay in the worker files with value 0 (mmap entries cannot be deleted).
_IDENTITY_METRICS = frozenset({"credit_model_info"})


def multiprocess_dir() -> Path | None:
    """Directory of the multiprocess metric files, or None in single-process mode."""
    value = os.environ.get(MULTIPROC_DIR_ENV)
    return Path(value) if value else None


def reset_multiprocess_dir(path: Path) -> None:
    """Empty (or create) the metric files directory; call once before workers start."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def mark_worker_dead(pid: int, path: Path | None = None) -> None:
    """Drop a dead worker's live-gauge files so its values stop being exposed."""
    directory = path or multiprocess_dir()
    if directory is not None:
        mark_process_dead(pid, str(directory))


class _DropRetiredIdentities(Collector):
    def __init__(self, inner: Collector) -> None:
        self._inner = inner

    def collect(self) -> Iterable[Metric]:
        for family in self._inner.collect():
            if family.name in _IDENTITY_METRICS:
                family.samples = [sample for sample in family.samples if sample.value != 0]
            yield family


def _read_stat(proc_root: Path, pid: int) -> list[str] | None:
    try:
        raw = (proc_root / str(pid) / "stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    # Fields after the parenthesised command name (which may contain spaces); index 0 is field 3 (state).
    return raw[raw.rfind(")") + 2 :].split()


class ProcessTreeCollector(Collector):
    """CPU time and resident memory of a process and its direct children, read from ``/proc``.

    CPU time includes the root's ``cutime``/``cstime`` (children it has already reaped),
    so the counter does not drop when gunicorn replaces a worker.
    """

    def __init__(self, root_pid: int, proc_root: str | Path = "/proc") -> None:
        self._root_pid = root_pid
        self._proc_root = Path(proc_root)
        self._ticks = os.sysconf("SC_CLK_TCK")
        self._page_size = os.sysconf("SC_PAGE_SIZE")

    def _children(self) -> Iterator[list[str]]:
        try:
            entries = list(self._proc_root.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.name.isdigit() or int(entry.name) == self._root_pid:
                continue
            fields = _read_stat(self._proc_root, int(entry.name))
            if fields and len(fields) > 21 and int(fields[1]) == self._root_pid:
                yield fields

    def collect(self) -> Iterable[Metric]:
        """Yield the summed CPU counter and resident memory gauge (nothing if the root is gone)."""
        root = _read_stat(self._proc_root, self._root_pid)
        if not root or len(root) < 22:
            return
        # stat fields: utime=14, stime=15, cutime=16, cstime=17, rss=24 (pages).
        cpu_ticks = sum(int(value) for value in root[11:15])
        rss_pages = int(root[21])
        for child in self._children():
            cpu_ticks += int(child[11]) + int(child[12])
            rss_pages += int(child[21])
        yield CounterMetricFamily(
            "process_cpu_seconds",
            "Total user and system CPU time of the API master and workers in seconds.",
            value=cpu_ticks / self._ticks,
        )
        yield GaugeMetricFamily(
            "process_resident_memory_bytes",
            "Resident memory of the API master and workers in bytes.",
            value=rss_pages * self._page_size,
        )


def build_multiprocess_registry(path: Path, root_pid: int | None = None) -> CollectorRegistry:
    """Registry merging every worker's metrics plus the process-tree collector."""
    registry = CollectorRegistry()
    registry.register(_DropRetiredIdentities(MultiProcessCollector(None, str(path))))
    master_pid = root_pid or int(os.environ.get(MASTER_PID_ENV) or os.getppid())
    registry.register(ProcessTreeCollector(master_pid))
    return registry
