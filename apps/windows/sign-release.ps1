<#
Signs the Windows installer of a GitHub release with the company's code signing certificate on this computer
(Certum SimplySign: sign in to SimplySign Desktop with the code from the phone first, so the certificate shows up),
then puts the signed installer back on the release.

Needs: SimplySign Desktop (signed in), the Windows SDK (signtool.exe) and the GitHub CLI (gh auth login).

  .\sign-release.ps1                 # newest release
  .\sign-release.ps1 -Tag v3.8.0     # a given release
#>
param(
    [string]$Tag = "",
    [string]$Repo = "LetsManu/officehub",
    [string]$Thumbprint = "",
    [string]$TimestampUrl = "http://time.certum.pl"
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI (gh) not found: https://cli.github.com" }

# signtool from the Windows SDK, x64 (SimplySign's driver is 64-bit)
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found: install the Windows SDK (Signing Tools for Desktop Apps)" }

# The code signing certificate SimplySign put into the personal store
if (-not $Thumbprint) {
    $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) } |
        Sort-Object NotAfter -Descending | Select-Object -First 1
    if (-not $cert) { throw "No code signing certificate found: sign in to SimplySign Desktop first" }
    $Thumbprint = $cert.Thumbprint
    Write-Host "Certificate: $($cert.Subject) (valid until $($cert.NotAfter.ToString('yyyy-MM-dd')))"
}

if (-not $Tag) { $Tag = (gh release view --repo $Repo --json tagName --jq .tagName) }
Write-Host "Release: $Tag"

$work = Join-Path ([IO.Path]::GetTempPath()) "officehub-sign-$Tag"
New-Item -ItemType Directory -Force $work | Out-Null
$file = Join-Path $work "OfficeHub-Setup.exe"
Remove-Item $file -ErrorAction SilentlyContinue
gh release download $Tag --repo $Repo --pattern OfficeHub-Setup.exe --dir $work
if ($LASTEXITCODE -ne 0) { throw "Download failed" }

$existing = Get-AuthenticodeSignature $file
if ($existing.Status -eq "Valid") { Write-Host "Already signed by $($existing.SignerCertificate.Subject)"; exit 0 }

& $signtool.FullName sign /sha1 $Thumbprint /tr $TimestampUrl /td SHA256 /fd SHA256 /d OfficeHub $file
if ($LASTEXITCODE -ne 0) { throw "Signing failed (is SimplySign Desktop still signed in?)" }

$signature = Get-AuthenticodeSignature $file
if ($signature.Status -ne "Valid") { throw "The installer is not validly signed: $($signature.Status)" }
Write-Host "Signed by: $($signature.SignerCertificate.Subject)"

gh release upload $Tag $file --repo $Repo --clobber
if ($LASTEXITCODE -ne 0) { throw "Upload failed" }
Write-Host "Done: the signed installer is on release $Tag."
