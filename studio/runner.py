import subprocess
import threading
import queue


class ProcessRunner:
    """Run a command in a background thread and stream output back to Tk."""

    def __init__(self, master, on_output, on_done):
        self.master = master
        self.on_output = on_output
        self.on_done = on_done
        self._queue = queue.Queue()
        self._proc = None
        self._thread = None
        self._poll()

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def run(self, args, cwd=None):
        if self.running:
            raise RuntimeError("Already running a task; wait for it to finish.")
        self._queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker, args=(list(args), cwd), daemon=True
        )
        self._thread.start()

    def _worker(self, args, cwd):
        try:
            self._proc = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            for line in self._proc.stdout:
                self._queue.put(("out", line))
            rc = self._proc.wait()
            self._queue.put(("done", rc))
        except Exception as exc:  # pragma: no cover - GUI safety net
            self._queue.put(("out", f"[启动失败] {exc}\n"))
            self._queue.put(("done", -1))

    def _poll(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "out":
                    self.on_output(payload)
                elif kind == "done":
                    self.on_done(payload)
        except queue.Empty:
            pass
        self.master.after(100, self._poll)
