# Интеграция GitHub Codespaces для нейросетевых моделей

## Возможно ли это?

**Да, это возможно.** GitHub Codespaces предоставляет полноценную среду разработки
в облаке, к которой можно программно подключаться через GitHub CLI, REST API
и GitHub Actions.

---

## 🔧 Способ 1. GitHub CLI (`gh codespace`)

Самый простой способ для интерактивной отладки:

```bash
# Создать codespace из репозитория
gh codespace create --repo owner/repo --branch main

# Выполнить команду внутри codespace (ssh)
gh codespace ssh --command "python script.py"

# Остановить codespace (чтобы не тратить квоту)
gh codespace stop --codespace <name>

# Удалить codespace
gh codespace delete --codespace <name>
```

**Python-функция для запуска кода:**

```python
import subprocess, json, time

def run_in_codespace(repo_spec: str, command: str, branch: str = "main",
                     timeout: int = 300) -> dict:
    """
    Создаёт codespace, запускает команду, возвращает stdout/stderr.
    Автоматически останавливает codespace после завершения.
    """
    # 1. Создать codespace
    create = subprocess.run(
        ["gh", "codespace", "create", "--repo", repo_spec,
         "--branch", branch, "--json"],
        capture_output=True, text=True, timeout=60
    )
    if create.returncode != 0:
        return {"error": f"create failed: {create.stderr}"}
    
    data = json.loads(create.stdout)
    cs_name = data.get("name", "")
    
    try:
        # 2. Выполнить команду
        exec = subprocess.run(
            ["gh", "codespace", "ssh", "--codespace", cs_name, "--command", command],
            capture_output=True, text=True, timeout=timeout
        )
        result = {
            "exit_code": exec.returncode,
            "stdout": exec.stdout,
            "stderr": exec.stderr,
            "codespace": cs_name,
        }
    finally:
        # 3. Остановить codespace
        subprocess.run(
            ["gh", "codespace", "stop", "--codespace", cs_name],
            capture_output=True, timeout=30
        )
    
    return result
```

**Требования:** установленный GitHub CLI, аутентификация (`gh auth login`).

---

## 🌐 Способ 2. GitHub REST API (Python)

Управление codespace через HTTP-запросы, без CLI:

```python
import requests, os, json

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

def create_codespace(owner: str, repo: str, branch: str = "main",
                     machine: str = "basicLinux32gb") -> dict:
    """Создаёт codespace для указанного репозитория."""
    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/codespaces",
        headers=HEADERS,
        json={"ref": branch, "machine": machine},
        timeout=30
    )
    if resp.status_code not in (200, 201):
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    return resp.json()

def run_in_codespace_api(codespace_name: str, command: str) -> dict:
    """Запускает команду в существующем codespace."""
    # Прямого API для запуска команд нет — используем предварительный
    # скрипт, который codespace выполняет при старте, или SSH поверх API.
    # Альтернатива: создать файл .devcontainer/postStart.sh в репозитории.
    return {
        "note": "Для запуска команд используйте GitHub CLI (см. способ 1)",
        "codespace": codespace_name,
    }

def stop_codespace(codespace_name: str) -> dict:
    """Останавливает codespace."""
    resp = requests.post(
        f"https://api.github.com/user/codespaces/{codespace_name}/stop",
        headers=HEADERS, timeout=30
    )
    return {"status": resp.status_code}

def list_codespaces() -> list:
    """Список всех codespace текущего пользователя."""
    resp = requests.get(
        "https://api.github.com/user/codespaces",
        headers=HEADERS, timeout=30
    )
    return resp.json().get("codespaces", [])
```

**Преимущество:** полный контроль через HTTP, можно встраивать в блокнот.
**Недостаток:** нет прямого API для выполнения произвольных команд (только CLI).

---

## ⚙️ Способ 3. GitHub Actions (рекомендуется)

Самый безопасный и бесплатный способ для CI/CD:

```yaml
# .github/workflows/test-model.yml
name: Test model
on:
  workflow_dispatch:        # ручной запуск
  pull_request:             # автоматически на PR
    paths:
      - '**.py'
      - '**.ipynb'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt 2>/dev/null || true
          pip install pytest pytest-html
      - name: Run tests
        run: python -m pytest --html=report.html --self-contained-html
      - name: Upload test report
        uses: actions/upload-artifact@v4
        with:
          name: test-report
          path: report.html
```

**Запуск из блокнота через `workflow_dispatch`:**

```python
import requests

def trigger_workflow(owner: str, repo: str, workflow_file: str,
                     ref: str = "main", inputs: dict = None):
    """Запускает GitHub Actions workflow из блокнота."""
    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/"
        f"{workflow_file}/dispatches",
        headers={
            "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json",
        },
        json={"ref": ref, "inputs": inputs or {}},
        timeout=30
    )
    return resp.status_code == 204  # 204 = успешно
```

---

## 📋 Что добавить в существующий блокнот

В `benchmark-task-agentic-github-api-keys.ipynb` можно добавить новую ячейку
с импортом модуля `codespaces_utils.py` (см. соседний файл) и функцией:

```python
# Новая ячейка в блокноте — после секции с gh_* инструментами
from codespaces_utils import run_in_codespace, trigger_workflow

# Пример: запустить тесты в codespace
result = run_in_codespace("mlaa4ml/KaggleModelsRepo", "python -m pytest")
print(result["stdout"][:2000] if "stdout" in result else result)
```

## 🎯 Рекомендация

| Сценарий | Решение |
|----------|---------|
| Автоматические тесты | **GitHub Actions** — бесплатно, безопасно, квоты 2000 мин/мес |
| Интерактивная отладка | **GitHub Codespaces** — нужна квота, но есть полный терминал |
| Из блокнота | **CLI** (`gh codespace`) — проще всего встроить в `subprocess` |

---

## ⚠️ Важно

- Codespaces требует **квоты** (бесплатно 60 ч/мес для аккаунтов GitHub Free,
  180 ч/мес для Pro)
- GitHub CLI должен быть установлен и аутентифицирован в среде запуска
- При использовании из Kaggle/Colab CLI не установлен — используйте REST API
  или GitHub Actions
- Для работы с `gh` нужен токен с scope `codespace:write`