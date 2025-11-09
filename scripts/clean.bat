@echo off
cd /d "%~dp0"
if exist "..\data" (
    for /d %%x in ("..\data\*") do rd /s /q "%%x" 2>nul
    del /q "..\data\*.*" 2>nul
    echo success
) else (
    echo data folder not found or empty
)