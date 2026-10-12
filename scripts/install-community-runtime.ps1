#requires -Version 7.2
<#
Install the approved Community toolchain only on an ephemeral Windows CI runner.
The owner explicitly authorized VS Community installation/use under the linked terms.
This script does not certify the owner's licensing eligibility or alter account,
telemetry, security, update-policy, or machine-wide environment settings.

Official references checked 2026-10-12:
https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022
https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-community?view=vs-2022
https://github.com/microsoft/vswhere/wiki/Examples
https://learn.microsoft.com/en-us/cpp/build/reference/headers?view=msvc-170
https://learn.microsoft.com/en-us/cpp/build/reference/dependents?view=msvc-170
https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/

Only the five enumerated DLLs and provenance.json become generated build inputs.
Do not upload the DLLs as standalone assets. Integration must package them into the
application, preserve Microsoft notices, and rerun native/OCR/Qt/EXE acceptance.
#>
[CmdletBinding()]
param(
    [switch] $AcceptCommunityLicense,
    [string] $RepositoryRoot = $env:GITHUB_WORKSPACE,
    [ValidateRange(5, 30)]
    [int] $InstallTimeoutMinutes = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:FailureExitCode = 1
$BootstrapperUrl = 'https://aka.ms/vs/17/release/vs_community.exe'
$LicenseUrl = 'https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/'
$ProductId = 'Microsoft.VisualStudio.Product.Community'
$Components = @(
    'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
    'Microsoft.VisualStudio.Component.VC.Redist.14.Latest'
)
$RequiredFiles = @('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
$MinimumRuntimeVersion = [version] '14.44.35211.0'
$Report = [ordered]@{
    schema_version = 1
    source = 'Microsoft Visual Studio Community 2022'
    license_url = $LicenseUrl
    redistribution_list_url = 'https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution'
    verified = $false
    status = 'not-verified'
    minimum_file_version = $MinimumRuntimeVersion.ToString()
    product = $null
    installer = $null
    tool = $null
    files = @()
}

function Assert-Condition([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
}

function Get-Hash([string] $Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-RegularPath([string] $Path, [string] $Root) {
    $full = [IO.Path]::GetFullPath($Path)
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    Assert-Condition ($full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) 'File is outside its approved root.'
    Assert-Condition (Test-Path -LiteralPath $full -PathType Leaf) 'Expected file is missing.'
    $cursor = Get-Item -LiteralPath $full -Force
    while ($null -ne $cursor) {
        Assert-Condition (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Reparse points are not accepted for verified tool/runtime inputs.'
        if ([string]::Equals($cursor.FullName.TrimEnd('\', '/'), $base, [StringComparison]::OrdinalIgnoreCase)) { break }
        $cursor = if ($cursor -is [IO.FileInfo]) { $cursor.Directory } else { $cursor.Parent }
    }
    return $full
}

function Get-MicrosoftSignature([string] $Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    Assert-Condition ($signature.Status.ToString() -eq 'Valid') 'Microsoft Authenticode validation failed.'
    Assert-Condition ($null -ne $signature.SignerCertificate) 'Authenticode signer certificate is missing.'
    $subject = $signature.SignerCertificate.Subject
    Assert-Condition ($subject -match '(?:^|,\s*)O=Microsoft Corporation(?:,|$)') 'Executable was not signed by Microsoft Corporation.'
    return [ordered]@{
        signature_status = 'Valid'
        signer_subject = $subject
        signer_thumbprint = $signature.SignerCertificate.Thumbprint
    }
}

function Invoke-BoundedProcess {
    param([string] $Path, [string[]] $Arguments, [int] $TimeoutSeconds, [string] $WorkingDirectory)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Path
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WorkingDirectory = $WorkingDirectory
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    # Child-process language only, to make dumpbin's machine line deterministic.
    $start.Environment['VSLANG'] = '1033'
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        Assert-Condition ($process.Start()) 'Could not start the approved Microsoft tool.'
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $script:FailureExitCode = 124
            # Stop only this launched process tree, never unrelated installer services.
            try { $process.Kill($true); $null = $process.WaitForExit(5000) } catch { }
            throw 'Approved Microsoft operation exceeded its time limit; do not continue packaging.'
        }
        # A detached child must not keep redirected pipe reads alive indefinitely.
        if (-not [Threading.Tasks.Task]::WhenAll([Threading.Tasks.Task[]] @($stdout, $stderr)).Wait(5000)) {
            $script:FailureExitCode = 124
            throw 'Microsoft tool output did not close within the diagnostic time limit.'
        }
        $outText = $stdout.GetAwaiter().GetResult()
        $errText = $stderr.GetAwaiter().GetResult()
        Assert-Condition (($outText.Length + $errText.Length) -le 4MB) 'Microsoft tool output exceeded the diagnostic limit.'
        return [pscustomobject]@{ ExitCode = $process.ExitCode; StdOut = $outText; StdErr = $errText }
    }
    finally { $process.Dispose() }
}

function Assert-NativeSuccess($Result, [string] $Operation) {
    if ($Result.ExitCode -ne 0) {
        $script:FailureExitCode = [int] $Result.ExitCode
        # Preserve actual exit codes (including 3010/740/1618). No reboot or elevation.
        throw "$Operation returned exit code $($Result.ExitCode); no verified runtime will be produced."
    }
}

function Save-OfficialBootstrapper([string] $Destination) {
    # HTTPS only; do not send credentials or accept a custom certificate policy.
    $allowedHosts = @('aka.ms', 'download.visualstudio.microsoft.com', 'download.microsoft.com')
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(180)
    $cancel = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(180))
    $uri = [uri] $BootstrapperUrl
    try {
        for ($hop = 0; $hop -le 5; $hop++) {
            Assert-Condition (($uri.Scheme -eq 'https') -and ($allowedHosts -contains $uri.DnsSafeHost) -and [string]::IsNullOrEmpty($uri.UserInfo)) 'Bootstrapper redirect left the approved official HTTPS hosts.'
            $response = $client.GetAsync($uri, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cancel.Token).GetAwaiter().GetResult()
            try {
                $status = [int] $response.StatusCode
                if ($status -in @(301, 302, 303, 307, 308)) {
                    Assert-Condition (($hop -lt 5) -and ($null -ne $response.Headers.Location)) 'Bootstrapper redirect limit or invalid redirect.'
                    $uri = [uri]::new($uri, $response.Headers.Location)
                    continue
                }
                Assert-Condition ($status -eq 200) "Official bootstrapper download returned HTTP $status."
                if ($null -ne $response.Content.Headers.ContentLength) {
                    Assert-Condition (($response.Content.Headers.ContentLength -gt 0) -and ($response.Content.Headers.ContentLength -le 16MB)) 'Unexpected bootstrapper content length.'
                }
                $inputStream = $response.Content.ReadAsStreamAsync($cancel.Token).GetAwaiter().GetResult()
                $outputStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try {
                    $buffer = [byte[]]::new(65536)
                    $total = 0L
                    while (($read = $inputStream.ReadAsync($buffer, 0, $buffer.Length, $cancel.Token).GetAwaiter().GetResult()) -gt 0) {
                        $total += $read
                        Assert-Condition ($total -le 16MB) 'Bootstrapper exceeded the download byte limit.'
                        $outputStream.Write($buffer, 0, $read)
                    }
                    Assert-Condition ($total -ge 100KB) 'Bootstrapper is implausibly small.'
                }
                finally { $outputStream.Dispose(); $inputStream.Dispose() }
                return $uri.AbsoluteUri
            }
            finally { $response.Dispose() }
        }
        throw 'Official bootstrapper could not be downloaded within the redirect limit.'
    }
    finally { $cancel.Dispose(); $client.Dispose(); $handler.Dispose() }
}

function Read-VersionSelector([string] $Path, [string] $Root) {
    $full = Assert-RegularPath $Path $Root
    Assert-Condition ((Get-Item -LiteralPath $full).Length -le 128) 'Unexpected version selector size.'
    $value = ([IO.File]::ReadAllText($full)).Trim()
    Assert-Condition ($value -match '^14\.[0-9]{1,3}\.[0-9]{1,6}$') 'Invalid VC tool/redist version selector.'
    return $value
}

function Assert-PeAmd64Dll([string] $Path) {
    $length = (Get-Item -LiteralPath $Path).Length
    Assert-Condition (($length -ge 1024) -and ($length -le 8MB)) 'Unexpected runtime DLL size.'
    $bytes = [IO.File]::ReadAllBytes($Path)
    Assert-Condition (($bytes.Length -ge 1024) -and ($bytes.Length -le 8MB)) 'Unexpected runtime DLL size.'
    Assert-Condition (($bytes[0] -eq 0x4D) -and ($bytes[1] -eq 0x5A)) 'Runtime file is not PE/MZ.'
    $offset = [BitConverter]::ToInt32($bytes, 0x3C)
    Assert-Condition (($offset -ge 0x40) -and ($offset -le ($bytes.Length - 26))) 'Invalid PE header offset.'
    Assert-Condition ([BitConverter]::ToUInt32($bytes, $offset) -eq 0x00004550) 'Invalid PE signature.'
    Assert-Condition ([BitConverter]::ToUInt16($bytes, $offset + 4) -eq 0x8664) 'Runtime is not AMD64.'
    Assert-Condition (([BitConverter]::ToUInt16($bytes, $offset + 22) -band 0x2000) -ne 0) 'Runtime PE image is not a DLL.'
    Assert-Condition ([BitConverter]::ToUInt16($bytes, $offset + 24) -eq 0x020B) 'Runtime DLL is not PE32+.'
}

function Read-AllowedDependencies([string] $Output) {
    # Parse both ordinary and delay-load import sections. Reject every unexpected
    # row inside those sections rather than silently dropping an unknown DLL.
    $allowedExact = $RequiredFiles + @('kernel32.dll', 'kernelbase.dll', 'ntdll.dll', 'ucrtbase.dll')
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $inSection = $false
    $sawSection = $false
    $sawSummary = $false
    foreach ($line in ($Output -split '\r?\n')) {
        $value = $line.Trim()
        if ($value -match '^Image has the following (?:delay load )?dependencies:$') {
            $inSection = $true
            $sawSection = $true
            continue
        }
        if (-not $inSection -or [string]::IsNullOrWhiteSpace($value)) { continue }
        if ($value -eq 'Summary') { $sawSummary = $true; break }
        $name = $value.ToLowerInvariant()
        Assert-Condition ($name -match '^[a-z0-9][a-z0-9_.-]{0,126}\.dll$') 'Unexpected dumpbin dependency row.'
        $isOsApiSet = $name -match '^(?:api-ms-win|ext-ms-win)-[a-z0-9]+(?:-[a-z0-9]+)*-l[0-9]+-[0-9]+-[0-9]+\.dll$'
        Assert-Condition (($allowedExact -contains $name) -or $isOsApiSet) "Runtime imports an unapproved dependency: $name"
        $null = $names.Add($name)
        Assert-Condition ($names.Count -le 64) 'Runtime dependency count exceeded the review limit.'
    }
    Assert-Condition ($sawSection -and $sawSummary -and ($names.Count -gt 0)) 'No complete nonempty runtime dependency inventory was produced.'
    return @($names | Sort-Object)
}

try {
    Assert-Condition ([bool] $AcceptCommunityLicense) 'Explicit -AcceptCommunityLicense is required under the owner-approved Community terms.'
    Assert-Condition ($IsWindows -and [Environment]::Is64BitProcess) 'Use 64-bit PowerShell 7 on Windows.'
    Assert-Condition (($env:GITHUB_ACTIONS -eq 'true') -and ($env:RUNNER_OS -eq 'Windows') -and ($env:RUNNER_ENVIRONMENT -eq 'github-hosted')) 'This install is restricted to an ephemeral GitHub-hosted Windows runner.'
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    Assert-Condition ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Runner lacks its normal admin capability; no elevation will be requested.'
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($RepositoryRoot)) 'RepositoryRoot is required.'
    $root = [IO.Path]::GetFullPath($RepositoryRoot)
    Assert-Condition ([string]::Equals($root.TrimEnd('\', '/'), [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE).TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) 'Output is restricted to this workflow workspace.'
    Assert-Condition (Test-Path -LiteralPath $root -PathType Container) 'Workflow workspace is missing.'
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) 'Runner temporary directory is unavailable.'
    $temporary = [IO.Path]::GetFullPath($env:RUNNER_TEMP)
    Assert-Condition (Test-Path -LiteralPath $temporary -PathType Container) 'Runner temporary directory is missing.'
    $installPath = Join-Path $temporary 'vga-vs2022-community'
    $buildRoot = Join-Path $root 'build'
    if (Test-Path -LiteralPath $buildRoot) {
        $buildItem = Get-Item -LiteralPath $buildRoot -Force
        Assert-Condition ($buildItem.PSIsContainer -and (($buildItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)) 'Generated build root must be a real workspace directory.'
    }
    $destination = Join-Path $buildRoot 'microsoft-runtime'
    Assert-Condition (-not (Test-Path -LiteralPath $installPath)) 'Proposed Community installation path already exists; refusing reuse or modification.'
    Assert-Condition (-not (Test-Path -LiteralPath $destination)) 'Generated runtime destination already exists; refusing overwrite.'
    $work = Join-Path $temporary ('vga-community-setup-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $work
    $bootstrapper = Join-Path $work 'vs_community.exe'
    $finalDownloadUrl = Save-OfficialBootstrapper $bootstrapper
    $bootstrapper = Assert-RegularPath $bootstrapper $work
    $bootstrapperSignature = Get-MicrosoftSignature $bootstrapper
    $Report.installer = [ordered]@{
        url = $BootstrapperUrl
        resolved_url = $finalDownloadUrl
        sha256 = Get-Hash $bootstrapper
        signature_status = $bootstrapperSignature.signature_status
        signer_subject = $bootstrapperSignature.signer_subject
        signer_thumbprint = $bootstrapperSignature.signer_thumbprint
        requested_components = $Components
        community_license_accepted = $true
        timeout_minutes = $InstallTimeoutMinutes
        exit_code = $null
    }
    # Individual components only; do not add entire workloads, recommended/optional
    # features, accounts, product keys, telemetry switches or security settings.
    $arguments = @('--quiet', '--wait', '--norestart', '--installPath', $installPath)
    foreach ($component in $Components) { $arguments += @('--add', $component) }
    $install = Invoke-BoundedProcess $bootstrapper $arguments ($InstallTimeoutMinutes * 60) $work
    $Report.installer.exit_code = $install.ExitCode
    Assert-NativeSuccess $install 'Visual Studio Community installation'

    $installerRoot = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer'
    $vswhere = Assert-RegularPath (Join-Path $installerRoot 'vswhere.exe') $installerRoot
    $vswhereSignature = Get-MicrosoftSignature $vswhere
    $queryArgs = @('-all', '-products', $ProductId, '-version', '[17.0,18.0)', '-requires') + $Components + @('-format', 'json', '-utf8')
    $query = Invoke-BoundedProcess $vswhere $queryArgs 30 $work
    Assert-NativeSuccess $query 'Official installed vswhere inventory'
    $instances = @($query.StdOut | ConvertFrom-Json -Depth 20)
    $matching = @($instances | Where-Object {
        ($_.productId -eq $ProductId) -and
        [string]::Equals([IO.Path]::GetFullPath($_.installationPath).TrimEnd('\', '/'), $installPath.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)
    })
    Assert-Condition ($matching.Count -eq 1) 'The exact newly installed Community instance was not identified.'
    $instance = $matching[0]
    $installationVersion = [version] $instance.installationVersion
    Assert-Condition (($installationVersion.Major -eq 17) -and ($instance.isComplete -is [bool]) -and $instance.isComplete -and ($instance.isLaunchable -is [bool]) -and $instance.isLaunchable) 'Community 2022 instance is incomplete or not launchable.'
    Assert-Condition (($instance.isRebootRequired -is [bool]) -and (-not $instance.isRebootRequired)) 'Community requires a reboot; refusing unverified continuation.'
    $Report.product = [ordered]@{
        id = $instance.productId
        installation_path = $installPath
        installation_version = $installationVersion.ToString()
        is_complete = $true
        is_launchable = $true
        is_reboot_required = $false
        vswhere_path = $vswhere
        vswhere_sha256 = Get-Hash $vswhere
        vswhere_signature_status = $vswhereSignature.signature_status
    }
    $toolsVersion = Read-VersionSelector (Join-Path $installPath 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') $installPath
    $redistVersion = Read-VersionSelector (Join-Path $installPath 'VC/Auxiliary/Build/Microsoft.VCRedistVersion.default.txt') $installPath
    $dumpbin = Assert-RegularPath (Join-Path $installPath "VC/Tools/MSVC/$toolsVersion/bin/Hostx64/x64/dumpbin.exe") $installPath
    $dumpbinSignature = Get-MicrosoftSignature $dumpbin
    $Report.tool = [ordered]@{
        path = $dumpbin
        sha256 = Get-Hash $dumpbin
        used = 'dumpbin /headers'
        dependency_check = 'dumpbin /dependents'
        signature_status = $dumpbinSignature.signature_status
        signer_subject = $dumpbinSignature.signer_subject
        tools_version = $toolsVersion
        redist_version = $redistVersion
    }
    $crtDirectory = Join-Path $installPath "VC/Redist/MSVC/$redistVersion/x64/Microsoft.VC143.CRT"
    Assert-Condition (Test-Path -LiteralPath $crtDirectory -PathType Container) 'This Community installation has no exact x64 VC143 release CRT directory.'
    $staging = Join-Path $work 'runtime-stage'
    $null = New-Item -ItemType Directory -Path $staging
    foreach ($filename in $RequiredFiles) {
        $source = Assert-RegularPath (Join-Path $crtDirectory $filename) $installPath
        Assert-PeAmd64Dll $source
        $signature = Get-MicrosoftSignature $source
        $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($source)
        $version = [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart)
        Assert-Condition (($version.Major -eq 14) -and ($version -ge $MinimumRuntimeVersion)) 'A licensed runtime DLL is older than the wheel-required 14.44.35211.0 floor.'
        $inspection = Invoke-BoundedProcess $dumpbin @('/nologo', '/headers', $source) 30 (Split-Path -Parent $dumpbin)
        Assert-NativeSuccess $inspection 'Installed Community dumpbin /headers'
        Assert-Condition ($inspection.StdOut -match '(?im)^\s*8664\s+machine\s+\(x64\)\s*$') 'dumpbin did not identify an x64 runtime DLL.'
        $imports = Invoke-BoundedProcess $dumpbin @('/nologo', '/dependents', $source) 30 (Split-Path -Parent $dumpbin)
        Assert-NativeSuccess $imports 'Installed Community dumpbin /dependents'
        $dependencies = @(Read-AllowedDependencies $imports.StdOut)
        $hash = Get-Hash $source
        $copy = Join-Path $staging $filename
        Copy-Item -LiteralPath $source -Destination $copy
        Assert-Condition ((Get-Hash $copy) -eq $hash) 'Runtime copy SHA256 mismatch.'
        $Report.files += [ordered]@{
            filename = $filename
            size = (Get-Item -LiteralPath $copy).Length
            sha256 = $hash
            file_version = $version.ToString()
            source_path = $source
            signature_status = $signature.signature_status
            signer_subject = $signature.signer_subject
            signer_thumbprint = $signature.signer_thumbprint
            machine = 'x64'
            dependencies = $dependencies
        }
    }
    Assert-Condition ($Report.files.Count -eq 5) 'Incomplete exact runtime file set.'
    $Report.status = 'passed'
    $Report.verified = $true
    $json = $Report | ConvertTo-Json -Depth 12
    Assert-Condition ([Text.Encoding]::UTF8.GetByteCount($json) -le 65536) 'Runtime provenance exceeds the bounded JSON size.'
    [IO.File]::WriteAllText((Join-Path $staging 'provenance.json'), $json + "`n", [Text.UTF8Encoding]::new($false))
    $null = New-Item -ItemType Directory -Path (Join-Path $root 'build') -Force
    # Commit generated inputs only once the complete exact set has passed.
    Move-Item -LiteralPath $staging -Destination $destination
    Write-Output $json
    exit 0
}
catch {
    $Report.verified = $false
    $Report.status = 'failed'
    $Report['error'] = $_.Exception.Message.Substring(0, [Math]::Min(1000, $_.Exception.Message.Length))
    $Report['exit_code'] = $script:FailureExitCode
    $json = $Report | ConvertTo-Json -Depth 12
    if ([Text.Encoding]::UTF8.GetByteCount($json) -le 65536) { Write-Output $json }
    else { Write-Output '{"schema_version":1,"verified":false,"status":"failed","error":"Diagnostic size limit"}' }
    exit $script:FailureExitCode
}
