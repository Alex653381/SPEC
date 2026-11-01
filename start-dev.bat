@echo off
setlocal
cd /d "%~dp0"

set APP_MODE=private
set DATABASE_PATH=data/demo-synthetic.db
set HOST=127.0.0.1
set PORT=8000

start "SPEC backend" .venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
start "SPEC frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
echo Close each window to stop the corresponding service.
endlocal
