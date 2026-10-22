#requires -Version 7.2
<#
Prepare one verified x64 CDB on a disposable GitHub-hosted Windows runner.
This is not a debugger launcher and never changes postmortem, security or symbol
settings. Reuse the standard SDK CDB first. Only if absent, the caller may elect
one official SDK Debugging Tools feature installation under the exact approved
license. Changed public terms stop before the installer executes; hidden
bootstrapper terms are not claimed to have been inspected.

Official references:
https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/debugger-download-tools
https://learn.microsoft.com/en-us/windows/apps/windows-sdk/downloads
https://github.com/microsoft/ebpf-for-windows/blob/main/.github/skills/debug-crash-dump/SKILL.md

Full tool paths, download URLs and installer metadata stay in build/owned-crash.
The diagnostic harness must project a sanitized allowlist for any upload.
#>
[CmdletBinding()]
param(
    [switch] $AcceptSdkLicense,
    [string] $RepositoryRoot = $env:GITHUB_WORKSPACE,
    [string] $ProofPath = 'build/owned-crash/debugger.json',
    [ValidateRange(1, 10)]
    [int] $InstallTimeoutMinutes = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$InstallerUrl = 'https://go.microsoft.com/fwlink/?linkid=2382321'
$LicenseUrl = 'https://aka.ms/WinSDKLicenseURL'
$LicenseSha256 = 'dd07eb178e00c6bba4148457fc00ff77cd4887eb521d504186fe59c9ec8bbe62'
$LicenseBytes = 246945
$Feature = 'OptionId.WindowsDesktopDebuggers'
$script:Stage = 'preconditions'
$script:FailureExitCode = 1
$script:ProofDestination = $null
$Report = [ordered]@{
    schema_version = 1
    status = 'not_verified'
    cdb = $null
    installation = [ordered]@{
        performed = $false
        exit_code = $null
        feature = $Feature
        installer = $null
        license = $null
    }
    input_files = [ordered]@{}
    helper_files = [ordered]@{}
}

function Assert-Condition([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
}

function Assert-RegularPath([string] $Path, [string] $Root, [switch] $Directory) {
    $full = [IO.Path]::GetFullPath($Path)
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    Assert-Condition ($full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) 'Path left the approved root.'
    $item = Get-Item -LiteralPath $full -Force
    Assert-Condition ($item.PSIsContainer -eq [bool] $Directory) 'Unexpected path type.'
    $cursor = $item
    while ($null -ne $cursor) {
        Assert-Condition (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Reparse points are forbidden.'
        if ([string]::Equals($cursor.FullName.TrimEnd('\', '/'), $base, [StringComparison]::OrdinalIgnoreCase)) { break }
        $cursor = if ($cursor -is [IO.FileInfo]) { $cursor.Directory } else { $cursor.Parent }
    }
    return $full
}

function Get-FileRecord([string] $Path, [string] $Root, [long] $MaxBytes = 32MB) {
    $full = Assert-RegularPath $Path $Root
    $size = (Get-Item -LiteralPath $full).Length
    Assert-Condition (($size -ge 0) -and ($size -le $MaxBytes)) 'File exceeds its bounded size.'
    return [ordered]@{
        sha256 = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $size
    }
}

function Get-SignedTool([string] $Path, [string] $Root, [switch] $RequireAmd64) {
    $full = Assert-RegularPath $Path $Root
    $record = Get-FileRecord $full $Root 32MB
    Assert-Condition ($record.size -ge 1024) 'Tool file is implausibly small.'
    $bytes = [IO.File]::ReadAllBytes($full)
    Assert-Condition (($bytes[0] -eq 0x4d) -and ($bytes[1] -eq 0x5a)) 'Tool is not a PE/MZ image.'
    $offset = [BitConverter]::ToInt32($bytes, 0x3c)
    Assert-Condition (($offset -ge 0x40) -and ($offset -le ($bytes.Length - 26))) 'Invalid tool PE offset.'
    Assert-Condition ([BitConverter]::ToUInt32($bytes, $offset) -eq 0x00004550) 'Invalid tool PE signature.'
    $machine = [BitConverter]::ToUInt16($bytes, $offset + 4)
    if ($RequireAmd64) {
        Assert-Condition (($machine -eq 0x8664) -and ([BitConverter]::ToUInt16($bytes, $offset + 24) -eq 0x020b)) 'CDB must be native x64.'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $full
    Assert-Condition (($signature.Status.ToString() -eq 'Valid') -and ($null -ne $signature.SignerCertificate)) 'Tool signature is not valid.'
    $subject = $signature.SignerCertificate.Subject
    Assert-Condition (($subject.Length -le 512) -and ($subject -match '(?:^|,\s*)O=Microsoft Corporation(?:,|$)')) 'Tool signer is not Microsoft Corporation.'
    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($full)
    $fileVersion = '{0}.{1}.{2}.{3}' -f $version.FileMajorPart, $version.FileMinorPart, $version.FileBuildPart, $version.FilePrivatePart
    Assert-Condition (($version.FileMajorPart -eq 10) -and ($version.FileBuildPart -ge 19041)) 'Unsupported Windows debugging tool version.'
    $record.signature_status = 'Valid'
    $record.signer_subject = $subject
    $record.file_version = $fileVersion
    if ($RequireAmd64) { $record.machine = 'x64' }
    return $record
}

function Save-OfficialFile([string] $Url, [string] $Destination, [long] $MaxBytes, [long] $MinimumBytes) {
    # Validate each hop before issuing it. No ambient account/token credentials,
    # HTTP fallback, certificate overrides, redirects to arbitrary hosts or retry.
    $allowedHosts = @('aka.ms', 'go.microsoft.com', 'download.microsoft.com', 'download.visualstudio.microsoft.com')
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseDefaultCredentials = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(120)
    $cancel = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(120))
    $uri = [uri] $Url
    try {
        for ($hop = 0; $hop -le 5; $hop++) {
            Assert-Condition (($uri.Scheme -eq 'https') -and ($uri.Port -eq 443) -and ($allowedHosts -contains $uri.DnsSafeHost) -and [string]::IsNullOrEmpty($uri.UserInfo)) 'Download left the approved official HTTPS hosts.'
            $response = $client.GetAsync($uri, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cancel.Token).GetAwaiter().GetResult()
            try {
                $status = [int] $response.StatusCode
                if ($status -in @(301, 302, 303, 307, 308)) {
                    Assert-Condition (($hop -lt 5) -and ($null -ne $response.Headers.Location)) 'Official download redirect limit.'
                    $uri = [uri]::new($uri, $response.Headers.Location)
                    continue
                }
                Assert-Condition ($status -eq 200) 'Official download did not succeed.'
                if ($null -ne $response.Content.Headers.ContentLength) {
                    Assert-Condition (($response.Content.Headers.ContentLength -ge $MinimumBytes) -and ($response.Content.Headers.ContentLength -le $MaxBytes)) 'Official download content length is outside its budget.'
                }
                $inputStream = $response.Content.ReadAsStreamAsync($cancel.Token).GetAwaiter().GetResult()
                $outputStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try {
                    $buffer = [byte[]]::new(65536)
                    $total = 0L
                    while (($read = $inputStream.ReadAsync($buffer, 0, $buffer.Length, $cancel.Token).GetAwaiter().GetResult()) -gt 0) {
                        $total += $read
                        Assert-Condition ($total -le $MaxBytes) 'Official download exceeded its byte limit.'
                        $outputStream.Write($buffer, 0, $read)
                    }
                    Assert-Condition ($total -ge $MinimumBytes) 'Official download is truncated.'
                }
                finally { $outputStream.Dispose(); $inputStream.Dispose() }
                return $uri.AbsoluteUri
            }
            finally { $response.Dispose() }
        }
        throw 'Official download could not be resolved.'
    }
    finally { $cancel.Dispose(); $client.Dispose(); $handler.Dispose() }
}

function Assert-NoPendingReboot {
    # Read only. Never clear or write an OS/global debugger setting.
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending', 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')) {
        Assert-Condition (-not (Test-Path -LiteralPath $key)) 'Runner has a pending reboot.'
    }
    $pending = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue
    Assert-Condition (($null -eq $pending) -or ($null -eq $pending.PendingFileRenameOperations) -or (@($pending.PendingFileRenameOperations).Count -eq 0)) 'Runner has pending reboot file operations.'
}

function Invoke-OneInstaller([string] $Installer, [string] $WorkingDirectory) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Installer
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WorkingDirectory = $WorkingDirectory
    foreach ($argument in @('/features', $Feature, '/quiet', '/norestart')) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        $Report.installation.performed = $true
        Assert-Condition ($process.Start()) 'Could not start the verified SDK installer.'
        if (-not $process.WaitForExit($InstallTimeoutMinutes * 60 * 1000)) {
            $script:FailureExitCode = 124
            try { $process.Kill($true); $null = $process.WaitForExit(5000) } catch { }
            throw 'SDK Debugging Tools installation exceeded its ten-minute cap.'
        }
        $Report.installation.exit_code = $process.ExitCode
        # Includes reboot-required 3010 and reboot-initiated 1641: both stop.
        if ($process.ExitCode -ne 0) {
            $script:FailureExitCode = $process.ExitCode
            throw 'SDK installer did not complete without a reboot.'
        }
    }
    finally { $process.Dispose() }
}

function Get-CheckoutFiles([string] $Root) {
    $head = (& git -C $Root rev-parse HEAD).Trim()
    Assert-Condition (($LASTEXITCODE -eq 0) -and ($head -cmatch '^[0-9a-f]{40}$') -and ($head -ceq $env:GITHUB_SHA)) 'Checkout differs from the dispatch SHA.'
    & git -C $Root diff HEAD --exit-code --quiet
    Assert-Condition ($LASTEXITCODE -eq 0) 'Tracked checkout changed.'
    $names = ((& git -C $Root ls-files -z) -join "`n").Split([char] 0, [StringSplitOptions]::RemoveEmptyEntries)
    Assert-Condition (($LASTEXITCODE -eq 0) -and ($names.Count -gt 0) -and ($names.Count -le 1024)) 'Unexpected tracked input inventory.'
    $records = [ordered]@{}
    foreach ($name in ($names | Sort-Object)) {
        Assert-Condition (($name.Length -le 240) -and (-not [IO.Path]::IsPathRooted($name)) -and ($name -notmatch '(^|/)\.\.?(/|$)|[\r\n\\:]')) 'Invalid tracked relative path.'
        $records[$name] = Get-FileRecord (Join-Path $Root $name) $Root
    }
    return $records
}

function Get-HelperFiles([string] $Root) {
    $records = [ordered]@{}
    foreach ($name in @('build/native/vga-wgc-capture.exe', 'build/native/wgc-capture-build.json', 'build/native/vga-wgc-session-capture.exe', 'build/native/wgc-session-capture-build.json')) {
        $records[$name] = Get-FileRecord (Join-Path $Root $name) $Root 4MB
    }
    return $records
}

function Save-Proof {
    if ($null -eq $script:ProofDestination) { return }
    $json = ($Report | ConvertTo-Json -Depth 10 -Compress) + "`n"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
    Assert-Condition ($bytes.Length -le 256KB) 'Local debugger proof exceeded its limit.'
    $stream = [IO.File]::Open($script:ProofDestination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
}

try {
    Assert-Condition ($IsWindows -and [Environment]::Is64BitProcess) 'Use native Windows x64 PowerShell 7.'
    Assert-Condition (($env:GITHUB_ACTIONS -eq 'true') -and ($env:RUNNER_OS -eq 'Windows') -and ($env:RUNNER_ENVIRONMENT -eq 'github-hosted')) 'Only an ephemeral GitHub-hosted Windows runner is permitted.'
    Assert-Condition (($env:GITHUB_REPOSITORY -ceq 'Junming-Liang/vga-aram-helper') -and ($env:GITHUB_EVENT_NAME -ceq 'workflow_dispatch') -and ($env:GITHUB_REF -ceq 'refs/heads/main') -and ($env:GITHUB_RUN_ATTEMPT -ceq '1')) 'Only the first manual main-branch attempt is permitted.'
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($RepositoryRoot)) 'Repository root is required.'
    $root = [IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\', '/')
    Assert-Condition ([string]::Equals($root, [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE).TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) 'Root must be this workflow workspace.'
    Assert-Condition ($ProofPath -ceq 'build/owned-crash/debugger.json') 'Only the build-local proof path is allowed.'
    $build = Join-Path $root 'build'
    $null = Assert-RegularPath $build $root -Directory
    $work = Join-Path $build 'owned-crash'
    Assert-Condition (-not (Test-Path -LiteralPath $work)) 'Debugger preparation must be fresh and cannot be retried.'
    $null = New-Item -ItemType Directory -Path $work
    $null = Assert-RegularPath $work $root -Directory
    $script:ProofDestination = Join-Path $root $ProofPath
    $script:Stage = 'input_snapshot'
    $Report.input_files = Get-CheckoutFiles $root
    $Report.helper_files = Get-HelperFiles $root
    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($programFiles)) 'Standard SDK installation root is missing.'
    $sdk = Join-Path $programFiles 'Windows Kits\10'
    $cdb = Join-Path $sdk 'Debuggers\x64\cdb.exe'
    $script:Stage = 'existing_cdb'
    if (-not (Test-Path -LiteralPath $cdb)) {
        Assert-Condition ([bool] $AcceptSdkLicense) 'Optional SDK installation requires the exact approved license.'
        Assert-NoPendingReboot
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        Assert-Condition ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Runner lacks its normal installer capability; no elevation is requested.'
        $script:Stage = 'license_download'
        $license = Join-Path $work 'sdk_license.rtf'
        $licenseResolved = Save-OfficialFile $LicenseUrl $license 1MB 1KB
        $licenseProof = Get-FileRecord $license $root 1MB
        Assert-Condition (($licenseProof.sha256 -ceq $LicenseSha256) -and ($licenseProof.size -eq $LicenseBytes)) 'SDK license bytes differ from the exact previously approved terms.'
        $licenseProof.resolved_url = $licenseResolved
        $licenseProof.binding = 'approved_public_sdk_license'
        $Report.installation.license = $licenseProof
        $script:Stage = 'installer_verification'
        $installer = Join-Path $work 'winsdksetup.exe'
        $installerResolved = Save-OfficialFile $InstallerUrl $installer 16MB 100KB
        $installerProof = Get-SignedTool $installer $root
        Assert-Condition ($installerProof.file_version -match '^10\.[01]\.26100\.[0-9]+$') 'Selected installer is not the reviewed 26100 SDK family.'
        $installerProof.resolved_url = $installerResolved
        $Report.installation.installer = $installerProof
        # The explicit grant covers this official 26100 SDK and the exact public
        # license above. No claim is made about inspecting hidden bootstrapper
        # terms. Any exposed extra agreement or changed version must stop review.
        $script:Stage = 'sdk_install'
        Invoke-OneInstaller $installer $work
        Assert-NoPendingReboot
    }
    $script:Stage = 'cdb_verification'
    $cdbProof = Get-SignedTool $cdb $sdk -RequireAmd64
    $cdbProof.path = [IO.Path]::GetFullPath($cdb)
    $Report.cdb = $cdbProof
    $script:Stage = 'input_recheck'
    $afterInputs = Get-CheckoutFiles $root
    $afterHelpers = Get-HelperFiles $root
    Assert-Condition (($Report.input_files | ConvertTo-Json -Compress) -ceq ($afterInputs | ConvertTo-Json -Compress)) 'Tracked source bytes changed during debugger preparation.'
    Assert-Condition (($Report.helper_files | ConvertTo-Json -Compress) -ceq ($afterHelpers | ConvertTo-Json -Compress)) 'Compiled helper bytes or manifests changed during debugger preparation.'
    $Report.status = 'verified'
    Save-Proof
    Write-Host 'Verified debugger proof is ready in build/owned-crash/debugger.json; no debugger has been launched.'
}
catch {
    $Report.status = 'failed'
    $Report.failure_stage = $script:Stage
    # Do not print exception strings, environment values, signer paths or logs.
    try { Save-Proof } catch { }
    Write-Host ('Debugger preparation stopped at stage: ' + $script:Stage + '. No diagnostic acceptance is claimed.')
    exit $script:FailureExitCode
}
