"""Single-process ownership of a local SQLite workspace, including recovery."""
import os
from pathlib import Path


class WorkspaceOwnershipError(RuntimeError):
    pass


class WorkspaceLock:
    def __init__(self, database_path):
        self.path = Path(database_path).resolve()
        self.stream = None

    def __enter__(self):
        if self.stream is not None:
            raise WorkspaceOwnershipError("Workspace ownership is already held.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.with_suffix(self.path.suffix + ".lock").open("a+b")
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise WorkspaceOwnershipError("This workspace is already in use. Stop its other app process before starting another.") from exc
        self.stream = stream
        return self

    def __exit__(self, *_):
        if self.stream:
            # Closing the descriptor releases the OS lock, including after a crash.
            self.stream.close()
            self.stream = None

    def require(self, database_path):
        if self.stream is None or self.stream.closed or self.path != Path(database_path).resolve():
            raise WorkspaceOwnershipError("Exclusive ownership of this workspace is required for upload recovery.")
