@echo off
echo ============================================
echo   Kevala Home - Auto Update Script
echo ============================================
echo.

echo [1/4] Extracting certificate data from PDFs...
python extract_certificates.py
if %errorlevel% neq 0 (
    echo ERROR: Extraction failed!
    pause
    exit /b 1
)
echo.

echo [2/4] Rebuilding index.html with embedded data...
python rebuild.py
if %errorlevel% neq 0 (
    echo ERROR: Rebuild failed!
    pause
    exit /b 1
)
echo.

echo [3/4] Adding changes to Git...
git add .
echo.

echo [4/4] Committing and pushing to GitHub...
set TIMESTAMP=%date:~0,2%-%date:~3,2%-%date:~6,4%_%time:~0,2%-%time:~3,2%
set TIMESTAMP=%TIMESTAMP: =0%
git commit -m "Update data and certificates [%TIMESTAMP%]"
git push origin main
echo.

echo ============================================
echo   Update complete!
echo   Visit: https://kevalahome.github.io/wbrera
echo ============================================
pause