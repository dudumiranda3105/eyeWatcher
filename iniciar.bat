@echo off
rem ============================================================================
rem  eyeWatcher - sobe tudo com dois cliques (Windows)
rem
rem  1. confere se o Docker esta instalado e, se estiver fechado, abre o Docker Desktop
rem  2. roda "docker compose up -d --build" (compila e inicia os 16 servicos)
rem  3. espera a aplicacao responder, mostra os logins e abre o navegador
rem
rem  Nao precisa configurar chave nenhuma: as senhas sao geradas sozinhas na
rem  primeira subida e ficam em secrets\CREDENCIAIS.txt.
rem ============================================================================
setlocal
cd /d "%~dp0"
title eyeWatcher - iniciando
set "URL=http://localhost:8080"

echo.
echo ===== eyeWatcher: iniciando =====
echo.

where docker >nul 2>nul
if errorlevel 1 goto sem_docker

docker info >nul 2>nul
if not errorlevel 1 goto docker_ok

echo O Docker Desktop esta fechado. Abrindo...
set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not exist "%DOCKER_EXE%" goto sem_docker
start "" "%DOCKER_EXE%"
set /a TENTATIVAS=0

:esperar_docker
docker info >nul 2>nul
if not errorlevel 1 goto docker_ok
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 48 goto docker_nao_subiu
echo Aguardando o Docker ficar pronto... %TENTATIVAS%/48
ping -n 6 127.0.0.1 >nul
goto esperar_docker

:docker_ok
echo Docker pronto. Subindo os servicos...
echo Na primeira vez demora: compila as imagens e baixa o modelo de IA, cerca de 2 GB.
echo.
docker compose up -d --build
if errorlevel 1 goto falhou

echo.
echo Aguardando a aplicacao responder em %URL% ...
set /a TENTATIVAS=0

:esperar_app
curl.exe -s -f -o nul %URL%/
if not errorlevel 1 goto app_ok
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 120 goto app_demorou
ping -n 4 127.0.0.1 >nul
goto esperar_app

:app_ok
echo.
echo ===== Pronto! =====
echo.
if exist "secrets\CREDENCIAIS.txt" type "secrets\CREDENCIAIS.txt"
echo.
echo Abrindo %URL% no navegador...
start "" %URL%
echo.
echo Obs.: o Assistente (IA) pode levar alguns minutos ate mostrar "Modelo pronto".
echo Para desligar tudo, de dois cliques em parar.bat
echo.
pause
exit /b 0

:sem_docker
echo O Docker nao foi encontrado neste computador.
echo.
echo Instale o Docker Desktop, abra ele uma vez e rode este arquivo de novo:
echo   https://www.docker.com/products/docker-desktop/
echo.
echo No Windows, a virtualizacao precisa estar ligada na BIOS.
start "" https://www.docker.com/products/docker-desktop/
pause
exit /b 1

:docker_nao_subiu
echo.
echo O Docker Desktop nao ficou pronto a tempo. Abra ele manualmente,
echo espere o icone da baleia parar de animar e rode este arquivo de novo.
pause
exit /b 1

:falhou
echo.
echo Algo deu errado ao subir os servicos. Leia as mensagens acima.
echo Para ver os detalhes: docker compose logs
pause
exit /b 1

:app_demorou
echo.
echo A aplicacao ainda nao respondeu. Os containers continuam subindo em segundo plano.
echo Confira com: docker compose ps
echo e abra %URL% quando todos estiverem "healthy".
pause
exit /b 1
