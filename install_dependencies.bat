@echo off
echo ====================================================
echo       YouTube Downloader Dependencies Installer
echo ====================================================
echo.

:: Check if Python is installed
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.8 or higher from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [1/5] Python is installed. Continuing...

:: Create virtual environment (optional)
echo.
echo [2/5] Setting up virtual environment...
if not exist .venv (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo WARNING: Could not create virtual environment.
        echo Will install packages globally instead.
    ) else (
        echo Virtual environment created successfully.
    )
) else (
    echo Using existing virtual environment.
)

:: Activate virtual environment if it exists
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo Virtual environment activated.
) else (
    echo Installing packages globally.
)

:: Install required Python packages
echo.
echo [3/5] Installing required Python packages...
pip install --upgrade pip
pip install yt-dlp pillow requests

:: Check if FFmpeg is already installed
echo.
echo [4/5] Checking for FFmpeg...
where ffmpeg > nul 2>&1
if %errorlevel% equ 0 (
    echo FFmpeg is already installed in your system.
) else (
    :: Download FFmpeg if not found
    echo FFmpeg not found in PATH. Downloading FFmpeg...
    
    if not exist ffmpeg.exe (
        echo Downloading FFmpeg from GitHub...
        powershell -Command "& {Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile 'ffmpeg.zip'}"
        
        echo Extracting FFmpeg...
        powershell -Command "& {Expand-Archive -Path 'ffmpeg.zip' -DestinationPath 'ffmpeg_temp' -Force}"
        
        echo Moving FFmpeg to current directory...
        copy "ffmpeg_temp\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe" "ffmpeg.exe"
        
        echo Cleaning up temporary files...
        rmdir /s /q ffmpeg_temp
        del ffmpeg.zip
        
        echo FFmpeg has been downloaded and placed in the current directory.
    ) else (
        echo FFmpeg found in current directory.
    )
)

:: Create a shortcut to run the application
echo.
echo [5/5] Creating shortcuts...
echo @echo off > run_ytdownloader.bat
echo if exist .venv\Scripts\activate.bat ( >> run_ytdownloader.bat
echo     call .venv\Scripts\activate.bat >> run_ytdownloader.bat
echo ) >> run_ytdownloader.bat
echo python YTDownloader2025v7.1.py >> run_ytdownloader.bat
echo pause >> run_ytdownloader.bat

echo.
echo ====================================================
echo       Installation Complete!
echo ====================================================
echo.
echo All dependencies for YTDownloader2025v7.1.py have been installed.
echo.
echo To run the application, use the run_ytdownloader.bat file
echo or execute "python YTDownloader2025v7.1.py" from the command line.
echo.
echo Press any key to exit...
pause > nul 