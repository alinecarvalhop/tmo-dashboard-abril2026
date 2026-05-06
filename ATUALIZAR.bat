@echo off
echo ========================================
echo  Atualizando Dashboard TMO...
echo ========================================
python "%~dp0atualizar_dashboard.py"
if %errorlevel% neq 0 (
    echo ERRO ao executar o script Python.
    pause
)
