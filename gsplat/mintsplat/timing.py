import time
from contextlib import contextmanager


class Timer:
    """Wall-clock per stage, synchronised with the GPU so async kernels are counted where they run."""

    def __init__(self):
        self.t: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        import torch

        torch.cuda.synchronize()
        t0 = time.perf_counter()
        try:
            yield
        finally:
            torch.cuda.synchronize()
            self.t[name] = round(time.perf_counter() - t0, 2)
            print(f"[time] {name}: {self.t[name]}s", flush=True)

    def total(self) -> float:
        return round(sum(self.t.values()), 2)
