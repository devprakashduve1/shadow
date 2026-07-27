import json
import subprocess
import sys
from unittest import mock

from assistant.dev_server import detect_start_command, launch_and_open_chrome


# -- detect_start_command ------------------------------------------------------------


def test_detect_start_command_prefers_dev_over_start(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js", "dev": "vite"}}))
    assert detect_start_command(tmp_path) == ["npm", "run", "dev"]


def test_detect_start_command_falls_back_to_start(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
    assert detect_start_command(tmp_path) == ["npm", "run", "start"]


def test_detect_start_command_falls_back_to_serve(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"serve": "http-server ."}}))
    assert detect_start_command(tmp_path) == ["npm", "run", "serve"]


def test_detect_start_command_none_when_no_recognized_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}))
    assert detect_start_command(tmp_path) is None


def test_detect_start_command_none_without_package_json(tmp_path):
    assert detect_start_command(tmp_path) is None


def test_detect_start_command_uses_pnpm_when_lockfile_present(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    (tmp_path / "pnpm-lock.yaml").write_text("")
    assert detect_start_command(tmp_path) == ["pnpm", "dev"]


def test_detect_start_command_uses_yarn_when_lockfile_present(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    (tmp_path / "yarn.lock").write_text("")
    assert detect_start_command(tmp_path) == ["yarn", "dev"]


def test_detect_start_command_handles_malformed_json(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    assert detect_start_command(tmp_path) is None


# -- launch_and_open_chrome ------------------------------------------------------------


def test_launch_and_open_chrome_detects_url_and_opens_it(tmp_path):
    log_dir = tmp_path / "logs"
    project = tmp_path / "project"
    project.mkdir()
    command = [
        sys.executable,
        "-c",
        "import time; print('Local: http://localhost:5173/', flush=True); time.sleep(30)",
    ]

    with mock.patch("assistant.dev_server._open_in_chrome") as open_mock:
        result = launch_and_open_chrome(project, command, timeout=10, log_dir=log_dir)

    try:
        assert result.url == "http://localhost:5173/"
        open_mock.assert_called_once_with("http://localhost:5173/")
        assert result.log_path.exists()
    finally:
        result.process.terminate()
        result.process.wait(timeout=5)


def test_launch_and_open_chrome_no_url_within_timeout(tmp_path):
    log_dir = tmp_path / "logs"
    project = tmp_path / "project"
    project.mkdir()
    command = [sys.executable, "-c", "import time; time.sleep(30)"]  # never prints a URL

    with mock.patch("assistant.dev_server._open_in_chrome") as open_mock:
        result = launch_and_open_chrome(project, command, timeout=1, log_dir=log_dir)

    try:
        assert result.url is None
        open_mock.assert_not_called()
    finally:
        result.process.terminate()
        result.process.wait(timeout=5)


def test_launch_and_open_chrome_process_exits_before_url(tmp_path):
    log_dir = tmp_path / "logs"
    project = tmp_path / "project"
    project.mkdir()
    command = [sys.executable, "-c", "print('no url here')"]  # exits immediately

    with mock.patch("assistant.dev_server._open_in_chrome") as open_mock:
        result = launch_and_open_chrome(project, command, timeout=5, log_dir=log_dir)

    assert result.url is None
    open_mock.assert_not_called()


def test_open_in_chrome_falls_back_when_chrome_not_registered():
    import webbrowser

    from assistant.dev_server import _open_in_chrome

    with mock.patch("webbrowser.get", side_effect=webbrowser.Error("no chrome")), mock.patch(
        "subprocess.run", side_effect=OSError("open not found")
    ), mock.patch("webbrowser.open") as fallback_open:
        _open_in_chrome("http://localhost:3000")

    fallback_open.assert_called_once_with("http://localhost:3000")
