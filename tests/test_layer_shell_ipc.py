import json
import socket
import threading

from layer_shell_ipc import send_command, socket_path


def test_socket_path_is_user_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert socket_path().parent == tmp_path
    assert str(socket_path().name).startswith("liam-")
    assert socket_path().name.endswith(".sock")


def test_socket_fallback_uses_private_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    path = socket_path()
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_send_command_writes_json(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = socket_path()
    received = []
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def receive():
        connection, _ = server.accept()
        with connection:
            received.append(json.loads(connection.recv(1024).decode()))

    thread = threading.Thread(target=receive)
    thread.start()
    send_command(path, "clear")
    thread.join(timeout=1)
    server.close()

    assert received == [{"command": "clear"}]
