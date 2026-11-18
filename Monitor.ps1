param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$monitorAddress = 'http://127.0.0.1:4862/'
$monitorOrigin = 'http://127.0.0.1:4862'
$logDirectory = Join-Path $env:TEMP 'DexterMonitor'

if (-not (Test-Path -LiteralPath $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}

$services = @{
    web = @{
        Name = 'Dexter.Web'
        ProjectPath = Join-Path $PSScriptRoot 'Dexter.Web\Dexter.Web.csproj'
        ProjectDirectory = Join-Path $PSScriptRoot 'Dexter.Web'
        Url = 'http://127.0.0.1:5226'
        LogPrefix = Join-Path $logDirectory 'web'
    }
    mcp = @{
        Name = 'Dexter.Mcp'
        ProjectPath = Join-Path $PSScriptRoot 'Dexter.Mcp\Dexter.Mcp.csproj'
        ProjectDirectory = Join-Path $PSScriptRoot 'Dexter.Mcp'
        Url = 'http://127.0.0.1:5071'
        LogPrefix = Join-Path $logDirectory 'mcp'
    }
}

function Get-ServiceProcesses {
    param([Parameter(Mandatory = $true)][hashtable]$Service)

    $projectDirectory = [System.IO.Path]::GetFullPath($Service.ProjectDirectory).TrimEnd('\')
    $projectPrefix = $projectDirectory + '\'
    $projectName = $Service.Name

    @(Get-CimInstance Win32_Process | Where-Object {
        $isProjectExecutable = $_.Name -ieq "$projectName.exe" -and
            $_.ExecutablePath -and
            $_.ExecutablePath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        $isProjectRunner = $_.Name -ieq 'dotnet.exe' -and
            $_.CommandLine -and
            $_.CommandLine.IndexOf($Service.ProjectPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0

        $isProjectExecutable -or $isProjectRunner
    })
}

function Get-ServiceStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][hashtable]$Service
    )

    $processes = @(Get-ServiceProcesses -Service $Service)
    [pscustomobject]@{
        id = $Key
        name = $Service.Name
        url = $Service.Url
        status = if ($processes.Count -gt 0) { 'running' } else { 'stopped' }
        processIds = @($processes | ForEach-Object { [int]$_.ProcessId })
    }
}

function Stop-DexterService {
    param([Parameter(Mandatory = $true)][hashtable]$Service)

    $processes = @(Get-ServiceProcesses -Service $Service)
    foreach ($process in $processes) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction Stop
    }

    $deadline = (Get-Date).AddSeconds(5)
    do {
        Start-Sleep -Milliseconds 200
        $remaining = @(Get-ServiceProcesses -Service $Service)
    } while ($remaining.Count -gt 0 -and (Get-Date) -lt $deadline)

    if ($remaining.Count -gt 0) {
        throw "Nao foi possivel parar todos os processos de $($Service.Name)."
    }
}

function Start-DexterService {
    param([Parameter(Mandatory = $true)][hashtable]$Service)

    if (-not (Test-Path -LiteralPath $Service.ProjectPath)) {
        throw "Projeto nao encontrado: $($Service.ProjectPath)"
    }

    if (@(Get-ServiceProcesses -Service $Service).Count -gt 0) {
        return
    }

    $stdoutPath = "$($Service.LogPrefix).stdout.log"
    $stderrPath = "$($Service.LogPrefix).stderr.log"
    $quotedProjectPath = '"{0}"' -f $Service.ProjectPath
    $arguments = "run --no-launch-profile --project $quotedProjectPath -- --urls $($Service.Url)"

    Start-Process -FilePath 'dotnet.exe' `
        -ArgumentList $arguments `
        -WorkingDirectory $Service.ProjectDirectory `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden | Out-Null
}

function Write-JsonResponse {
    param(
        [Parameter(Mandatory = $true)]$Context,
        [Parameter(Mandatory = $true)]$Value,
        [int]$StatusCode = 200
    )

    $body = [System.Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 5 -Compress))
    $Context.Response.StatusCode = $StatusCode
    $Context.Response.ContentType = 'application/json; charset=utf-8'
    $Context.Response.ContentLength64 = $body.Length
    $Context.Response.OutputStream.Write($body, 0, $body.Length)
}

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($monitorAddress)

try {
    $listener.Start()
    Write-Host "Monitor Dexter disponivel em $monitorAddress"
    Write-Host 'Pressione Ctrl+C para encerrar o monitor.'

    if (-not $NoBrowser) {
        Start-Process $monitorAddress
    }

    while ($listener.IsListening) {
        $context = $listener.GetContext()

        try {
            $request = $context.Request
            $path = $request.Url.AbsolutePath.TrimEnd('/')
            if ([string]::IsNullOrEmpty($path)) {
                $path = '/'
            }

            if ($request.HttpMethod -eq 'GET' -and ($path -eq '/' -or $path -eq '/monitor.html')) {
                $htmlPath = Join-Path $PSScriptRoot 'monitor.html'
                if (-not (Test-Path -LiteralPath $htmlPath)) {
                    throw 'O arquivo monitor.html nao foi encontrado na raiz do projeto.'
                }

                $body = [System.IO.File]::ReadAllBytes($htmlPath)
                $context.Response.ContentType = 'text/html; charset=utf-8'
                $context.Response.Headers['Cache-Control'] = 'no-store'
                $context.Response.ContentLength64 = $body.Length
                $context.Response.OutputStream.Write($body, 0, $body.Length)
            }
            elseif ($request.HttpMethod -eq 'GET' -and $path -eq '/api/status') {
                $status = @(
                    Get-ServiceStatus -Key 'web' -Service $services.web
                    Get-ServiceStatus -Key 'mcp' -Service $services.mcp
                )
                Write-JsonResponse -Context $context -Value @{ services = $status }
            }
            elseif ($request.HttpMethod -eq 'POST' -and $path -eq '/api/control') {
                if ($request.Headers['Host'] -ne '127.0.0.1:4862' -or
                    $request.Headers['Origin'] -ne $monitorOrigin) {
                    Write-JsonResponse -Context $context -Value @{ error = 'Origem nao permitida.' } -StatusCode 403
                }
                elseif (-not $request.ContentType -or
                    -not $request.ContentType.StartsWith('application/json', [System.StringComparison]::OrdinalIgnoreCase)) {
                    Write-JsonResponse -Context $context -Value @{ error = 'Envie uma requisicao JSON.' } -StatusCode 415
                }
                else {
                    $reader = [System.IO.StreamReader]::new($request.InputStream, $request.ContentEncoding)
                    try {
                        $payload = $reader.ReadToEnd() | ConvertFrom-Json
                    }
                    finally {
                        $reader.Dispose()
                    }

                    $key = [string]$payload.service
                    $action = [string]$payload.action
                    if (-not $services.ContainsKey($key) -or $action -notin @('start', 'stop', 'restart')) {
                        Write-JsonResponse -Context $context -Value @{ error = 'Servico ou acao invalida.' } -StatusCode 400
                    }
                    else {
                        $service = $services[$key]
                        if ($action -eq 'stop') {
                            Stop-DexterService -Service $service
                        }
                        else {
                            if ($action -eq 'restart') {
                                Stop-DexterService -Service $service
                            }
                            Start-DexterService -Service $service
                        }

                        Write-JsonResponse -Context $context -Value @{
                            service = Get-ServiceStatus -Key $key -Service $service
                        }
                    }
                }
            }
            else {
                Write-JsonResponse -Context $context -Value @{ error = 'Rota nao encontrada.' } -StatusCode 404
            }
        }
        catch {
            Write-Host "Erro no monitor: $($_.Exception.Message)" -ForegroundColor Red
            if ($context.Response.OutputStream.CanWrite) {
                try {
                    Write-JsonResponse -Context $context -Value @{ error = $_.Exception.Message } -StatusCode 500
                }
                catch {
                    Write-Host "Nao foi possivel enviar a resposta: $($_.Exception.Message)" -ForegroundColor Red
                }
            }
        }
        finally {
            $context.Response.Close()
        }
    }
}
finally {
    if ($listener.IsListening) {
        $listener.Stop()
    }
    $listener.Close()
}
