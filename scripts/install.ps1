# Instala Tokenizer en este equipo: entorno virtual, comando en PATH, reglas de firewall y diagnostico.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-SkipFirewall] [-SkipPath]
# Las reglas de firewall requieren PowerShell como administrador.
# Los nombres de las reglas deben coincidir con FIREWALL_RULES en src\tokenizer\config.py.

[CmdletBinding()]
param(
    [switch]$SkipFirewall,
    [switch]$SkipPath
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Find-Python {
    $candidates = @(
        @("py", "-3"),
        @("python"),
        @("python3")
    )
    $installed = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue
    foreach ($exe in $installed) { $candidates += ,@($exe.FullName) }
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $extra = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $check = & $exe @extra -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $check -eq "True") { return $candidate }
        } catch {
            continue
        }
    }
    throw "No encuentro Python 3.10 o superior. Instalalo desde python.org o con: winget install Python.Python.3.12"
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$python = Find-Python
$pythonExe = $python[0]
$pythonArgs = @($python | Select-Object -Skip 1)

$venv = Join-Path $repo ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$scripts = Join-Path $venv "Scripts"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creando entorno virtual en .venv ..."
    & $pythonExe @pythonArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual." }
}

Write-Host "Instalando Tokenizer ..."
& $venvPython -m pip install -q -e $repo
if ($LASTEXITCODE -ne 0) { throw "pip no pudo instalar Tokenizer." }

if ($SkipPath) {
    Write-Host "PATH: omitido (-SkipPath). Usa $scripts\tokenizer.exe o activa el venv."
} else {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($userPath -split ";" | Where-Object { $_ })
    if ($entries -contains $scripts) {
        Write-Host "PATH: ya contiene $scripts"
    } else {
        [Environment]::SetEnvironmentVariable("Path", (($entries + $scripts) -join ";"), "User")
        Write-Host "PATH: anadido $scripts al PATH del usuario (abre una terminal nueva)."
    }
}

$firewallRules = [ordered]@{
    "Tokenizer HTTP 8765"          = @("TCP", 8765)
    "Tokenizer descubrimiento 8766" = @("UDP", 8766)
}

if ($SkipFirewall) {
    Write-Host "Firewall: omitido (-SkipFirewall)."
} elseif (-not (Test-Administrator)) {
    Write-Warning "Sin permisos de administrador: no se crearon las reglas de firewall. Ejecuta el script como administrador o usa -SkipFirewall."
} else {
    foreach ($name in $firewallRules.Keys) {
        $protocol = $firewallRules[$name][0]
        $port = $firewallRules[$name][1]
        Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol $protocol -LocalPort $port -Action Allow -Profile Private,Domain | Out-Null
        Write-Host "Firewall: regla '$name' creada ($protocol $port, redes privadas)."
    }
}

Write-Host ""
Write-Host "Diagnostico:"
& (Join-Path $scripts "tokenizer.exe") doctor

Write-Host ""
Write-Host "Siguientes pasos:"
Write-Host "  Primer equipo de la red:  tokenizer setup --new"
Write-Host "  Unirse a una red:         tokenizer setup --join   (con el codigo de 'tokenizer pair' en el host)"
Write-Host "  Arrancar:                 tokenizer start"
