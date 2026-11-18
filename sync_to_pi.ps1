$PiHost = "pi@192.168.1.11"
$Dest   = "~/RaspbotV2-RTOS"

# Folders and files the robot needs
$Folders = @("motion", "vision", "scheduler", "tools", "docs")
$Files   = @("main.py", "config.py", "requirements.txt")

# Remove stale bytecode locally so it isn't copied
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

foreach ($f in $Folders) {
    if (Test-Path $f) { scp -r $f "${PiHost}:${Dest}/" }
}
foreach ($f in $Files) {
    if (Test-Path $f) { scp $f "${PiHost}:${Dest}/" }
}

# Clear stale bytecode on the Pi too
ssh $PiHost "find $Dest -name __pycache__ -type d -exec rm -rf {} +"
Write-Host "Sync done."