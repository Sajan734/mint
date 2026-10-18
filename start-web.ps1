# Opens Mint's web app: the buyer site on http://localhost:3000, with the seller app (port 3001) behind /sell.
# Installs any packages a pull added, replaces old Mint dev servers, starts both servers in their own (minimized)
# windows, then opens the browser. Close the two "Mint ..." windows to stop the servers.
#   .\start-web.ps1        (or right-click > Run with PowerShell)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$apps = @(@{ Name = "seller"; Port = 3001 }, @{ Name = "buyer"; Port = 3000 })

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is not installed (https://nodejs.org)." }
if (-not (Test-Path (Join-Path $root ".env"))) { Write-Warning "No .env in $root; the apps run on defaults (copy .env.example)." }

# Old servers: one left on 3001 makes /sell serve a stale build.
$old = Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object {
  $_.CommandLine -like "*$root\buyer\*next*" -or $_.CommandLine -like "*$root\seller\*next*"
}
foreach ($p in $old) {
  Write-Host "Stopping old server (PID $($p.ProcessId))"
  Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($app in $apps) {
  for ($i = 0; $i -lt 20 -and (Get-NetTCPConnection -State Listen -LocalPort $app.Port -ErrorAction SilentlyContinue); $i++) {
    Start-Sleep -Milliseconds 250
  }
  $busy = Get-NetTCPConnection -State Listen -LocalPort $app.Port -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($busy) {
    $name = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    throw "Port $($app.Port) is in use by $name (PID $($busy.OwningProcess)). Close it and run this again."
  }
}

foreach ($app in $apps) {
  Write-Host "Installing packages for $($app.Name)"
  # Run from the app's folder: corepack picks the pnpm version from the package.json where it runs (pnpm@9.15.9)
  Push-Location (Join-Path $root $app.Name)
  try { corepack pnpm install --frozen-lockfile } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "pnpm install failed in $($app.Name)." }
}

foreach ($app in $apps) {
  $title = "Mint $($app.Name) :$($app.Port)"
  Start-Process powershell -WorkingDirectory (Join-Path $root $app.Name) -WindowStyle Minimized `
    -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$title'; corepack pnpm dev"
}

Write-Host "Waiting for the servers..."
$deadline = (Get-Date).AddSeconds(90)
foreach ($app in $apps) {
  while (-not (Get-NetTCPConnection -State Listen -LocalPort $app.Port -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $deadline) { throw "The $($app.Name) server did not start; check its 'Mint $($app.Name)' window." }
    Start-Sleep -Milliseconds 500
  }
}

Start-Process "http://localhost:3000"
Write-Host "Mint is running at http://localhost:3000 (selling at /sell). Close the two Mint windows to stop it."
