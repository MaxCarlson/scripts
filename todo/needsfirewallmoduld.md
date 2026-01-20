╭─ pwsh     ~            07:38:52 
╰─Get-NetConnectionProfile | Select-Object Name,

╭─ pwsh     ~            07:38:25 
╰─stop-Process -Name python
╭─ pwsh     ~            07:38:38 
╰─Get-NetTCPConnection -LocalPort 61208 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
Get-NetTCPConnection: No matching MSFT_NetTCPConnection objects found by CIM query for instances of the ROOT/StandardCimv2/MSFT_NetTCPConnection class on the  CIM server: SELECT * FROM MSFT_NetTCPConnection  WHERE ((LocalPort = 61208)) AND ((State = 2)). Verify query parameters and retry.
╭─ pwsh     ~            07:38:52 
╰─Get-NetConnectionProfile | Select-Object Name,NetworkCategory

Name       NetworkCategory
----       ---------------
CaLAN 5Ghz         Private

╭─ pwsh     ~            07:39:35 
╰─New-NetFirewallRule -DisplayName "Glances WebUI TCP 61208" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 61208 -Profile Private,Domain

Name                          : {d092061b-fa9e-
                                4359-b41c-2df7b
                                b0389c5}
DisplayName                   : Glances WebUI
                                TCP 61208
Description                   :
DisplayGroup                  :
Group                         :
Enabled                       : True
Profile                       : Domain, Private
Platform                      : {}
Direction                     : Inbound
Action                        : Allow
EdgeTraversalPolicy           : Block
LooseSourceMapping            : False
LocalOnlyMapping              : False
Owner                         :
PrimaryStatus                 : OK
Status                        : The rule was
                                parsed
                                successfully
                                from the
                                store. (65536)
EnforcementStatus             : NotApplicable
PolicyStoreSource             : PersistentStore
PolicyStoreSourceType         : Local
RemoteDynamicKeywordAddresses : {}
PolicyAppId                   :
PackageFamilyName             :

╭─ pwsh     ~   693ms⠀
                 07:39:59 
╰─    self.flush(stats, cs_status=cs_status) 

