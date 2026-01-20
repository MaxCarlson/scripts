
# what is port doing/happeninv at port

╰─Get-NetTCPConnection -LocalPort 61208 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
                                                LocalAddress LocalPort OwningProcess            ------------ --------- -------------            0.0.0.0          61208          2392                    
# Find process using port
                                                ╭─ pwsh     ~            07:34:36 ╰─$p=(Get-NetTCPConnection -LocalPort 61208 -State Listen).OwningProcess; Get-Process -Id $p | Select-Object Id,ProcessName,Path                                                                  Id ProcessName Path                             -- ----------- ----                           2392 python      C:\Users\mcarls\AppData\Local… 
