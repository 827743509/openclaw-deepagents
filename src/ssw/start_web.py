from __future__ import annotations

import csv
import io
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import uvicorn

from ssw.config import (
    SSW_AGENT_PROTOCOL_HOST,
    SSW_AGENT_PROTOCOL_PORT,
    SSW_WEB_HOST,
    SSW_WEB_PORT,
    SSW_WORKSPACE,
)

WORKSPACE = Path(SSW_WORKSPACE).resolve()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LANGGRAPH_CONFIG_PATH = PROJECT_ROOT / "langgraph.json"
PACKAGE_DEFAULT_WORKSPACE = PROJECT_ROOT
WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AGENT_PROTOCOL_STARTUP_TIMEOUT_SECONDS = 30.0


def _copy_missing_files(source_dir: Path, target_dir: Path) -> bool:
    copied = False
    for source_path in source_dir.rglob("*"):
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        if target_path.exists():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied = True
    return copied


def _initialize_workspace() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "skills" / "main").mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "skills" / "text_to_sql").mkdir(parents=True, exist_ok=True)

    copied = False
    default_mcp_config = PACKAGE_DEFAULT_WORKSPACE / "mcp.json"
    target_mcp_config = WORKSPACE / "mcp.json"
    if default_mcp_config.is_file() and not target_mcp_config.exists():
        shutil.copy2(default_mcp_config, target_mcp_config)
        copied = True

    default_main_skills = PACKAGE_DEFAULT_WORKSPACE / "skills" / "main"
    if default_main_skills.is_dir():
        copied = _copy_missing_files(
            default_main_skills,
            WORKSPACE / "skills" / "main",
        ) or copied

    if copied:
        print("已初始化默认 MCP 配置和主 Agent skills", flush=True)


def _list_windows_listening_process_ids(port: int) -> set[int]:
    result = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
        check=False,
        creationflags=WINDOWS_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法查询端口 {port} 的监听进程")

    process_ids: set[int] = set()
    port_suffix = f":{port}"
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) < 5 or columns[0].upper() != "TCP":
            continue
        if not columns[1].endswith(port_suffix):
            continue
        if columns[-2].upper() != "LISTENING" or not columns[-1].isdigit():
            continue
        process_ids.add(int(columns[-1]))
    return process_ids


def _list_descendant_process_ids(parent_process_ids: set[int]) -> set[int]:
    if not parent_process_ids:
        return set()

    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId | "
        "ConvertTo-Csv -NoTypeInformation"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
        check=False,
        creationflags=WINDOWS_NO_WINDOW,
    )
    if result.returncode != 0:
        return set()

    children_by_parent: dict[int, set[int]] = {}
    for row in csv.DictReader(io.StringIO(result.stdout)):
        process_id = row.get("ProcessId", "")
        parent_process_id = row.get("ParentProcessId", "")
        if not process_id.isdigit() or not parent_process_id.isdigit():
            continue
        children_by_parent.setdefault(int(parent_process_id), set()).add(int(process_id))

    descendants: set[int] = set()
    pending_process_ids = list(parent_process_ids)
    while pending_process_ids:
        parent_process_id = pending_process_ids.pop()
        for process_id in children_by_parent.get(parent_process_id, set()):
            if process_id in descendants:
                continue
            descendants.add(process_id)
            pending_process_ids.append(process_id)
    return descendants


def _stop_windows_process_on_port(port: int) -> None:
    process_ids = _list_windows_listening_process_ids(port)
    if not process_ids:
        print(f"端口 {port} 当前未被占用", flush=True)
        return

    current_process_id = os.getpid()
    descendant_process_ids = _list_descendant_process_ids(process_ids)
    target_process_ids = [
        *sorted(descendant_process_ids - process_ids),
        *sorted(process_ids),
    ]
    for process_id in target_process_ids:
        if process_id == current_process_id:
            raise RuntimeError(f"不能终止当前进程：PID {process_id}")

        process_kind = "残留子进程" if process_id in descendant_process_ids else "监听进程树"
        print(f"正在终止端口 {port} 的{process_kind}：PID {process_id}", flush=True)
        subprocess.run(
            ["taskkill.exe", "/PID", str(process_id), "/T", "/F"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )

    for _ in range(20):
        remaining_process_ids = _list_windows_listening_process_ids(port)
        if not remaining_process_ids:
            print(f"端口 {port} 已清理完成", flush=True)
            return
        time.sleep(0.25)

    remaining_text = ", ".join(str(item) for item in sorted(remaining_process_ids))
    raise RuntimeError(
        f"端口 {port} 的进程无法终止，请检查权限。残留 PID：{remaining_text}"
    )


def _parse_process_ids(output: str) -> set[int]:
    return {int(value) for value in output.split() if value.isdigit()}


def _list_macos_listening_process_ids(port: int) -> set[int]:
    lsof_command = shutil.which("lsof")
    if not lsof_command:
        raise RuntimeError("macOS 缺少 lsof 命令，无法查询端口监听进程")

    result = subprocess.run(
        [lsof_command, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"无法查询 macOS 端口 {port} 的监听进程")
    return _parse_process_ids(result.stdout)


def _list_linux_listening_process_ids(port: int) -> set[int]:
    fuser_command = shutil.which("fuser")
    if fuser_command:
        result = subprocess.run(
            [fuser_command, "-n", "tcp", str(port)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError(f"无法查询 Linux 端口 {port} 的监听进程")
        return _parse_process_ids(result.stdout)

    lsof_command = shutil.which("lsof")
    if lsof_command:
        result = subprocess.run(
            [lsof_command, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError(f"无法查询 Linux 端口 {port} 的监听进程")
        return _parse_process_ids(result.stdout)

    raise RuntimeError("Linux 缺少 fuser 或 lsof 命令，无法查询端口监听进程")


def _list_posix_listening_process_ids(port: int) -> set[int]:
    if sys.platform == "darwin":
        return _list_macos_listening_process_ids(port)
    return _list_linux_listening_process_ids(port)


def _send_signal_to_processes(process_ids: set[int], signal_number: int) -> None:
    for process_id in sorted(process_ids):
        if process_id == os.getpid():
            raise RuntimeError(f"不能终止当前进程：PID {process_id}")
        try:
            os.kill(process_id, signal_number)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            raise RuntimeError(
                f"没有权限终止进程 PID {process_id}，请检查进程所属用户"
            ) from exc


def _stop_posix_process_on_port(port: int) -> None:
    process_ids = _list_posix_listening_process_ids(port)
    if not process_ids:
        print(f"端口 {port} 当前未被占用", flush=True)
        return

    system_name = "macOS" if sys.platform == "darwin" else "Linux"
    process_text = ", ".join(str(item) for item in sorted(process_ids))
    print(
        f"正在通过 {system_name} SIGTERM 终止端口 {port} 的进程：PID {process_text}",
        flush=True,
    )
    _send_signal_to_processes(process_ids, signal.SIGTERM)

    for _ in range(20):
        remaining_process_ids = _list_posix_listening_process_ids(port)
        if not remaining_process_ids:
            print(f"端口 {port} 已清理完成", flush=True)
            return
        time.sleep(0.25)

    print(f"端口 {port} 仍被占用，正在通过 SIGKILL 强制清理", flush=True)
    _send_signal_to_processes(remaining_process_ids, signal.SIGKILL)
    for _ in range(20):
        remaining_process_ids = _list_posix_listening_process_ids(port)
        if not remaining_process_ids:
            print(f"端口 {port} 已清理完成", flush=True)
            return
        time.sleep(0.25)

    remaining_text = ", ".join(str(item) for item in sorted(remaining_process_ids))
    raise RuntimeError(f"端口 {port} 的进程无法终止，残留 PID：{remaining_text}")


def stop_process_on_port(port: int) -> None:
    print(f"正在清理 Agent Protocol 端口 {port} 的残留进程", flush=True)
    if sys.platform == "win32":
        _stop_windows_process_on_port(port)
        return
    if sys.platform in {"darwin", "linux"}:
        _stop_posix_process_on_port(port)
        return
    raise RuntimeError(f"暂不支持当前操作系统：{sys.platform}")


def start_agent_protocol_process() -> subprocess.Popen[str]:
    if not LANGGRAPH_CONFIG_PATH.is_file():
        raise RuntimeError(f"缺少 LangGraph 配置文件：{LANGGRAPH_CONFIG_PATH}")

    executable = "langgraph.exe" if sys.platform == "win32" else "langgraph"
    command = [
        executable,
        "dev",
        "--config",
        str(LANGGRAPH_CONFIG_PATH),
        "--host",
        SSW_AGENT_PROTOCOL_HOST,
        "--port",
        str(SSW_AGENT_PROTOCOL_PORT),
        "--no-browser",
        "--no-reload",
    ]

    env = os.environ.copy()
    agent_protocol_url = (
        f"http://{SSW_AGENT_PROTOCOL_HOST}:"
        f"{SSW_AGENT_PROTOCOL_PORT}"
    )
    env["SSW_WORKSPACE"] = str(WORKSPACE)
    env["SSW_AGENT_PROTOCOL_URL"] = agent_protocol_url
    os.environ["SSW_AGENT_PROTOCOL_URL"] = agent_protocol_url

    if sys.platform == "win32":
        system_name = "Windows"
    elif sys.platform == "darwin":
        system_name = "macOS"
    elif sys.platform == "linux":
        system_name = "Linux"
    else:
        raise RuntimeError(f"暂不支持当前操作系统：{sys.platform}")

    print(
        f"正在通过 {system_name} 启动 Agent Protocol Server 服务：",
        " ".join(command),
        flush=True,
    )
    if sys.platform == "win32":
        return subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        start_new_session=True,
    )


def wait_for_agent_protocol_process(
    process: subprocess.Popen[str],
    timeout_seconds: float = AGENT_PROTOCOL_STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(
                "Agent Protocol Server 启动失败，"
                f"子进程退出码：{return_code}，请检查上方 LangGraph 日志。"
            )

        try:
            with socket.create_connection(
                (SSW_AGENT_PROTOCOL_HOST, SSW_AGENT_PROTOCOL_PORT),
                timeout=0.5,
            ):
                print(
                    "Agent Protocol Server 已就绪："
                    f"http://{SSW_AGENT_PROTOCOL_HOST}:{SSW_AGENT_PROTOCOL_PORT}",
                    flush=True,
                )
                return
        except OSError:
            time.sleep(0.1)

    raise RuntimeError(
        "Agent Protocol Server 启动超时："
        f"{timeout_seconds:g} 秒内未监听端口 {SSW_AGENT_PROTOCOL_PORT}。"
    )


def stop_agent_protocol_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    print("正在停止 Agent Protocol Server 服务", flush=True)
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
    elif sys.platform in {"darwin", "linux"}:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        raise RuntimeError(f"暂不支持当前操作系统：{sys.platform}")

    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


def main() -> None:
    print(f"正在使用 SSW 工作目录：{WORKSPACE}", flush=True)
    _initialize_workspace()

    stop_process_on_port(SSW_AGENT_PROTOCOL_PORT)
    agent_protocol_process = start_agent_protocol_process()

    try:
        wait_for_agent_protocol_process(agent_protocol_process)
        print(
            f"正在启动 FastAPI 服务：http://{SSW_WEB_HOST}:{SSW_WEB_PORT}",
            flush=True,
        )
        uvicorn.run(
            "ssw.server:app",
            host=SSW_WEB_HOST,
            port=SSW_WEB_PORT,
            reload=False,
            workers=1,
        )
    finally:
        stop_agent_protocol_process(agent_protocol_process)
        stop_process_on_port(SSW_AGENT_PROTOCOL_PORT)


if __name__ == "__main__":
    main()
