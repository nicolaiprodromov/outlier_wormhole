@echo off
if exist "data" (
    del /q "data\*.*" 2>nul
    for /d %%x in ("data\*") do rd /s /q "%%x" 2>nul
) else (
    echo data folder not found
)
if exist "data\raw_dumps" (
    del /q "data\raw_dumps\*.*" 2>nul
    for /d %%x in ("data\raw_dumps\*") do rd /s /q "%%x" 2>nul
) else (
    echo data\raw_dumps folder not found
)
echo success