rm .\results\*
rm -r .\stars\*
rm -r .\tmp\

cp ".\logs\*.log",".\logs\raw\*.log","*.log" .\results\
rm -r .\logs\
rm *.log
Get-ChildItem -Path ".\results\" -Filter *.log | Rename-Item -NewName { $_.BaseName + ".txt" }

