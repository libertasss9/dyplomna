from contextlib import contextmanager
from time import perf_counter


def _measure_value(value):
    return str(value).replace("\n", " ").replace("\r", " ").replace(" ", "_")


@contextmanager
def measure_operation(operation, df=None, **details):
    """Print internal timing for thesis measurements without changing API responses."""
    started = perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = perf_counter() - started
        parts = [
            "[MEASURE]",
            f"operation={operation}",
            f"status={status}",
            f"elapsed_s={elapsed:.3f}",
        ]
        if df is not None:
            parts.extend([f"rows={int(df.shape[0])}", f"columns={int(df.shape[1])}"])
        for key, value in details.items():
            if value is not None:
                parts.append(f"{key}={_measure_value(value)}")
        print(" ".join(parts), flush=True)
