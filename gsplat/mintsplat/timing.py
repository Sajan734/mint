import time
from contextlib import contextmanager


class Timer:
    """Wall-clock per stage, synchronised with the GPU so async kernels are counted where they run."""

    def __init__(self, on_event=None):
        """on_event(stage, status, ms) is called at start ("started"), end ("done") and on error ("failed")."""
        self.t: dict[str, float] = {}
        self.on_event = on_event or (lambda *a: None)

    @contextmanager
    def stage(self, name: str):
        import torch

        torch.cuda.synchronize()
        self.on_event(name, "started", 0)
        t0 = time.perf_counter()
        ok = False
        try:
            yield
            ok = True
        finally:
            torch.cuda.synchronize()
            self.t[name] = round(time.perf_counter() - t0, 2)
            self.on_event(name, "done" if ok else "failed", int(self.t[name] * 1000))
            print(f"[time] {name}: {self.t[name]}s", flush=True)

    def total(self) -> float:
        return round(sum(self.t.values()), 2)
