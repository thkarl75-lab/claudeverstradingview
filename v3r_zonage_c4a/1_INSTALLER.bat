@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Installation - V3R Zonage C-4a

echo.
echo ============================================================
echo   ETAPE 1 sur 3 : INSTALLATION
echo ============================================================
echo.
echo   Cette etape ne se fait QU'UNE SEULE FOIS.
echo   Elle telecharge les outils necessaires (2 a 5 minutes).
echo.

REM --- Verifie que Python est installe -----------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo   [PROBLEME] Python n'est pas installe sur cet ordinateur.
    echo.
    echo   Que faire :
    echo     1. Allez sur   https://www.python.org/downloads/
    echo     2. Cliquez sur le gros bouton jaune "Download Python"
    echo     3. Lancez le fichier telecharge
    echo     4. TRES IMPORTANT : cochez la case
    echo        "Add python.exe to PATH"  EN BAS de la fenetre
    echo        avant de cliquer sur "Install Now"
    echo     5. Une fois termine, relancez ce fichier 1_INSTALLER.bat
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   Python detecte : %%v
echo.

REM --- Cree un environnement isole ---------------------------------------
echo   Preparation de l'espace de travail...
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo   [PROBLEME] Impossible de creer l'environnement Python.
        echo   Envoyez une capture d'ecran de cette fenetre pour obtenir de l'aide.
        echo.
        pause
        exit /b 1
    )
)

REM --- Installe les bibliotheques ----------------------------------------
echo   Telechargement des outils cartographiques...
echo   (c'est normal que ce soit long, ne fermez pas la fenetre)
echo.
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   [PROBLEME] L'installation des outils a echoue.
    echo   Verifiez votre connexion Internet, puis relancez ce fichier.
    echo   Si le probleme persiste, envoyez une capture de cette fenetre.
    echo.
    pause
    exit /b 1
)

REM --- Verification que tout fonctionne ----------------------------------
echo.
echo   Verification de l'installation...
".venv\Scripts\python.exe" tests\test_pipeline.py
if errorlevel 1 (
    echo.
    echo   [ATTENTION] Certaines verifications ont echoue.
    echo   Envoyez une capture de cette fenetre pour obtenir de l'aide.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   INSTALLATION TERMINEE
echo ============================================================
echo.
echo   Vous pouvez maintenant double-cliquer sur :
echo.
echo     2_EXTRACTION.bat        pour obtenir le fichier Excel
echo     3_TABLEAU_DE_BORD.bat   pour voir la carte interactive
echo.
echo   Vous n'aurez plus jamais besoin de relancer 1_INSTALLER.bat.
echo.
pause
