"""
codespaces_utils.py — Утилиты для интеграции GitHub Codespaces с нейросетевыми моделями.

Позволяет моделям (агентам) запускать код из репозитория в GitHub Codespaces
или GitHub Actions, получать результаты и останавливать среды.

Использование в блокноте:
    from codespaces_utils import run_in_codespace, trigger_workflow, list_codespaces
"""

import json
import os
import subprocess
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# ---------------------------------------------------------------------------
# Способ 1. GitHub CLI (gh codespace)
# ---------------------------------------------------------------------------

def run_in_codespace(
    repo_spec: str,
    command: str,
    branch: str = "main",
    timeout: int = 300,
    auto_stop: bool = True,
) -> dict:
    """
    Создаёт codespace, запускает команду, возвращает stdout/stderr.

    Параметры:
        repo_spec: строка вида "owner/repo"
        command: команда для выполнения (например "python -m pytest")
        branch: ветка репозитория
        timeout: таймаут выполнения команды (сек)
        auto_stop: остановить codespace после выполнения

    Возвращает:
        dict с ключами: exit_code, stdout, stderr, codespace

    Требуется: установленный `gh` CLI, токен с scope codespace:write.
    """
    # 1. Создать codespace
    create = subprocess.run(
        ["gh", "codespace", "create", "--repo", repo_spec,
         "--branch", branch, "--json"],
        capture_output=True, text=True, timeout=60,
    )
    if create.returncode != 0:
        return {"error": f"create failed: {create.stderr.strip()}"}

    try:
        data = json.loads(create.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"json parse failed: {e}, output: {create.stdout[:200]}"}

    cs_name = data.get("name", "")
    if not cs_name:
        return {"error": "codespace name not found in response", "raw": create.stdout[:500]}

    # 2. Дождаться готовности codespace
    for attempt in range(6):
        status = subprocess.run(
            ["gh", "codespace", "view", "--codespace", cs_name, "--json", "state"],
            capture_output=True, text=True, timeout=30,
        )
        if status.returncode == 0:
            try:
                state_data = json.loads(status.stdout)
                if state_data.get("state") == "Available":
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(5 * (attempt + 1))

    try:
        # 3. Выполнить команду
        exec_result = subprocess.run(
            ["gh", "codespace", "ssh", "--codespace", cs_name, "--command", command],
            capture_output=True, text=True, timeout=timeout,
        )
        result = {
            "exit_code": exec_result.returncode,
            "stdout": exec_result.stdout,
            "stderr": exec_result.stderr,
            "codespace": cs_name,
        }
    except subprocess.TimeoutExpired:
        result = {
            "error": f"timeout ({timeout}s) exceeded",
            "codespace": cs_name,
        }
    finally:
        # 4. Остановить codespace
        if auto_stop:
            subprocess.run(
                ["gh", "codespace", "stop", "--codespace", cs_name],
                capture_output=True, timeout=30,
            )

    return result


def list_codespaces() -> list:
    """
    Возвращает список codespace текущего пользователя.

    Каждый элемент: dict с ключами name, state, repository, git_status.
    """
    try:
        result = subprocess.run(
            ["gh", "codespace", "list", "--json", "name,state,repository,gitStatus"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return [{"error": result.stderr.strip()}]
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return [{"error": str(e)}]


def stop_codespace(codespace_name: str) -> str:
    """Останавливает codespace по имени."""
    result = subprocess.run(
        ["gh", "codespace", "stop", "--codespace", codespace_name],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"
    return f"Codespace {codespace_name} остановлен."


def delete_codespace(codespace_name: str) -> str:
    """Удаляет codespace по имени."""
    result = subprocess.run(
        ["gh", "codespace", "delete", "--codespace", codespace_name, "--force"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"
    return f"Codespace {codespace_name} удалён."


# ---------------------------------------------------------------------------
# Способ 2. GitHub REST API
# ---------------------------------------------------------------------------

def _api_request(method: str, path: str, **kwargs) -> dict:
    """Внутренний helper для HTTP-запросов к GitHub API."""
    import requests

    resp = requests.request(
        method, f"{GITHUB_API}{path}",
        headers=HEADERS, timeout=30, **kwargs
    )
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    return resp.json()


def create_codespace_api(
    owner: str,
    repo: str,
    branch: str = "main",
    machine: str = "basicLinux32gb",
) -> dict:
    """
    Создаёт codespace через REST API.
    Возвращает объект codespace (или dict с ключом 'error').
    """
    return _api_request(
        "POST",
        f"/repos/{owner}/{repo}/codespaces",
        json={"ref": branch, "machine": machine},
    )


def stop_codespace_api(codespace_name: str) -> dict:
    """Останавливает codespace через REST API."""
    return _api_request("POST", f"/user/codespaces/{codespace_name}/stop")


def list_codespaces_api() -> list:
    """Список codespace через REST API."""
    data = _api_request("GET", "/user/codespaces")
    return data.get("codespaces", [data] if "error" in data else [])


# ---------------------------------------------------------------------------
# Способ 3. GitHub Actions (workflow_dispatch)
# ---------------------------------------------------------------------------

def trigger_workflow(
    owner: str,
    repo: str,
    workflow_file: str,
    ref: str = "main",
    inputs: Optional[dict] = None,
) -> str:
    """
    Запускает GitHub Actions workflow через workflow_dispatch.

    Параметры:
        owner: владелец репозитория
        repo: имя репозитория
        workflow_file: имя файла workflow (например 'test-model.yml')
        ref: ветка или тег
        inputs: dict с входными параметрами workflow

    Возвращает:
        str — сообщение об успехе или ошибке.
    """
    import requests

    resp = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows/"
        f"{workflow_file}/dispatches",
        headers=HEADERS,
        json={"ref": ref, "inputs": inputs or {}},
        timeout=30,
    )
    if resp.status_code == 204:
        return f"Workflow '{workflow_file}' запущен на {ref}."
    return (
        f"ERROR: HTTP {resp.status_code}: {resp.text[:200]}"
        " (нужен scope Actions: RW)"
    )


def get_workflow_runs(
    owner: str,
    repo: str,
    workflow_file: str,
    limit: int = 5,
) -> list:
    """
    Возвращает последние запуски workflow (для проверки статуса).
    """
    import requests

    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows/"
        f"{workflow_file}/runs",
        headers=HEADERS,
        params={"per_page": limit},
        timeout=30,
    )
    if resp.status_code != 200:
        return [{"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}]
    return resp.json().get("workflow_runs", [])


# ---------------------------------------------------------------------------
# Пример использования (main)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== codespaces_utils.py ===")
    print()
    print("Доступные функции:")
    print("  run_in_codespace(repo, command, branch, timeout, auto_stop)")
    print("  list_codespaces()")
    print("  stop_codespace(name)")
    print("  delete_codespace(name)")
    print("  create_codespace_api(owner, repo, branch, machine)")
    print("  trigger_workflow(owner, repo, workflow_file, ref, inputs)")
    print("  get_workflow_runs(owner, repo, workflow_file, limit)")
    print()
    print("Пример:")
    print('  result = run_in_codespace("mlaa4ml/KaggleModelsRepo", "python -m pytest")')
    print('  print(result.get("stdout", result)[:500])')