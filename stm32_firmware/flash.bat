@echo off
chcp 65001 >nul
set PYOCD=D:\Users\Lenovo\AppData\Local\Programs\Python\Python39\Scripts\pyocd.exe
set PACK=C:\RT-ThreadStudio\RT-ThreadStudio\RT-ThreadStudio\repo\Extract\Debugger_Support_Packages\RealThread\PyOCD\0.1.3\packs\Keil.STM32F4xx_DFP.2.14.0-small.pack
set BIN=%~dp0Debug\rtthread.bin

"%PYOCD%" flash -M under-reset --target=STM32F407VE --erase=auto --frequency=100000 --pack "%PACK%" "-Ocmsis_dap.limit_packets=1" "-Ocmsis_dap.deferred_transfers=false" "%BIN%"

pause