param(
  [string]$Entry = "radio_m3u.py",
  [string]$Name = "m3u_editor"
)

$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt

pyinstaller --noconfirm --clean --onefile --name $Name $Entry

Write-Host "Built: dist/$Name.exe"
