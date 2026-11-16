@echo off
rem  eyeWatcher - desliga os servicos mantendo os dados (Windows).
rem  Para apagar tudo (dados, modelos treinados e modelo do Ollama): docker compose down -v
setlocal
cd /d "%~dp0"
title eyeWatcher - parando

docker compose stop
if errorlevel 1 goto falhou

echo.
echo eyeWatcher parado. Os dados foram mantidos.
echo Para subir de novo, de dois cliques em iniciar.bat
pause
exit /b 0

:falhou
echo.
echo Nao consegui parar os servicos. O Docker Desktop esta aberto?
pause
exit /b 1
