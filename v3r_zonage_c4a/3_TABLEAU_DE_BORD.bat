@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tableau de bord - V3R Zonage C-4a

echo.
echo ============================================================
echo   TABLEAU DE BORD AVEC CARTE INTERACTIVE
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   [PROBLEME] L'installation n'a pas encore ete faite.
    echo.
    echo   Double-cliquez d'abord sur   1_INSTALLER.bat
    echo.
    pause
    exit /b 1
)

echo   Le tableau de bord va s'ouvrir dans votre navigateur Internet.
echo.
echo   IMPORTANT : gardez cette fenetre noire OUVERTE tant que
echo   vous utilisez le tableau de bord. Pour le fermer, revenez
echo   ici et appuyez sur les touches  Ctrl + C
echo.

".venv\Scripts\python.exe" -m streamlit run app.py

echo.
echo   Tableau de bord ferme.
pause
