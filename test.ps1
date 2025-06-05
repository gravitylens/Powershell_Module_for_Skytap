Import-Module -force ./Powershell_Module_for_Skytap/Skytap.psm1
Set-Authorization -tokenfile .\user_token

Get-Projects
$skytapenv = 129606952
get-Environment -configId $skytapenv
