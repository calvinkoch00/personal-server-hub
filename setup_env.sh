#!/usr/bin/env bash

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_BIN="python3"

echo "==> Prüfe Python-Installation..."
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo "Fehler: $PYTHON_BIN wurde nicht gefunden. Bitte installiere Python 3."
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "==> Erstelle virtuelles Environment unter .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "==> Virtuelles Environment (.venv) existiert bereits."
fi

echo "==> Aktiviere .venv..."
source "$VENV_DIR/bin/activate"

echo "==> Aktualisiere pip..."
pip install --upgrade pip

if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    echo "==> Installiere Pakete aus requirements.txt..."
    pip install -r "$PROJECT_ROOT/requirements.txt"
fi

echo "==> Installiere pytest..."
pip install pytest

echo "==> Konfiguriere .vscode/settings.json für Pylance..."
mkdir -p "$PROJECT_ROOT/.vscode"
cat << 'EOF' > "$PROJECT_ROOT/.vscode/settings.json"
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.analysis.extraPaths": [
    "${workspaceFolder}/aws_lambda"
  ],
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false
}
EOF

if [ -f "$PROJECT_ROOT/.gitignore" ]; then
    if ! grep -qs "^.venv" "$PROJECT_ROOT/.gitignore"; then
        echo -e "\n.venv/\n.pytest_cache/" >> "$PROJECT_ROOT/.gitignore"
        echo "==> .venv/ zu .gitignore hinzugefügt."
    fi
else
    echo -e ".venv/\n.pytest_cache/" > "$PROJECT_ROOT/.gitignore"
    echo "==> .gitignore mit .venv/ erstellt."
fi

echo ""
echo " Fertig eingerichtet!"
echo "Aktiviere die Umgebung bei Bedarf im Terminal mit: source .venv/bin/activate"