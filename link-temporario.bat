@echo off
rem Cria um link HTTPS temporario para o app rodando neste PC.
rem Requer o cloudflared: winget install --id Cloudflare.cloudflared
cd /d "%~dp0"
start "Servidor do app" python server.py 8000
timeout /t 2 >nul
echo Procure abaixo a linha com https://....trycloudflare.com e abra no celular.
cloudflared tunnel --url http://localhost:8000
pause
