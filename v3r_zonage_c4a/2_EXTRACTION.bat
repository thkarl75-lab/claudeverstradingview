@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Extraction - V3R Zonage C-4a

echo.
echo ============================================================
echo   EXTRACTION DES PROPRIETES C-4a
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

echo   Telechargement des donnees de la Ville de Trois-Rivieres
echo   et croisement avec le zonage. Patientez, cela peut prendre
echo   plusieurs minutes la premiere fois.
echo.

".venv\Scripts\python.exe" main.py
set CODE=%errorlevel%

echo.
if "%CODE%"=="0" (
    echo ============================================================
    echo   TERMINE - Le fichier Excel est pret
    echo ============================================================
    echo.
    echo   Ouverture du dossier des resultats...
    start "" "%~dp0exports"
) else if "%CODE%"=="1" (
    echo   [RESULTAT VIDE] Aucune propriete trouvee.
    echo   Les donnees ont ete lues, mais aucune zone C-4a n'en ressort.
    echo   Envoyez une capture de cette fenetre pour obtenir de l'aide.
) else (
    echo   [PROBLEME] Les donnees n'ont pas pu etre telechargees.
    echo   Lisez le message ci-dessus : il indique quoi faire.
    echo   Le plus souvent, il suffit de reessayer plus tard.
)

echo.
pause
