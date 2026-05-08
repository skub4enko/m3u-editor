[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [string]$Name,

  [Parameter(Mandatory)]
  [string]$SourceDir,

  [string]$OutputDir = (Get-Location).Path,

  [string[]]$Extensions = @(".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".wma"),

  [switch]$NoRecurse,

  [switch]$AbsolutePaths,

  [switch]$NoSort
)

$ErrorActionPreference = "Stop"

function Normalize-Extensions {
  param([string[]]$Exts)
  $Exts |
    Where-Object { $_ -and $_.Trim() } |
    ForEach-Object {
      $e = $_.Trim().ToLowerInvariant()
      if ($e[0] -ne ".") { $e = "." + $e }
      $e
    } |
    Select-Object -Unique
}

$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path

$normalizedExts = Normalize-Extensions $Extensions
if (-not $normalizedExts -or $normalizedExts.Count -eq 0) {
  throw "Extensions list is empty."
}

$playlistPath = Join-Path $OutputDir ($Name + ".m3u")
$playlistDir = Split-Path -Parent $playlistPath

$recurse = -not $NoRecurse
$files = Get-ChildItem -LiteralPath $SourceDir -File -Recurse:$recurse |
  Where-Object { $normalizedExts -contains $_.Extension.ToLowerInvariant() }

if (-not $NoSort) {
  $files = $files | Sort-Object FullName
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("#EXTM3U") | Out-Null

Push-Location $playlistDir
try {
  foreach ($f in $files) {
    if ($AbsolutePaths) {
      $lines.Add($f.FullName) | Out-Null
      continue
    }
    $rel = Resolve-Path -Relative -LiteralPath $f.FullName
    $lines.Add($rel) | Out-Null
  }
}
finally {
  Pop-Location
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($playlistPath, $lines, $utf8NoBom)

Write-Host ("Created: " + $playlistPath)
Write-Host ("Tracks:  " + $files.Count)
