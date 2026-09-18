param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,
    [string]$ExpectedThumbprint = ""
)

$ErrorActionPreference = "Stop"

$artifact = Resolve-Path -LiteralPath $ArtifactPath
$signature = Get-AuthenticodeSignature -FilePath $artifact.Path
if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Windows artifact is not Authenticode signed: $($artifact.Path) ($($signature.Status): $($signature.StatusMessage))"
}
if (-not $signature.SignerCertificate) {
    throw "Windows artifact has no signer certificate: $($artifact.Path)"
}
if ($ExpectedThumbprint -and $signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint) {
    throw "Windows artifact signer mismatch: expected $ExpectedThumbprint, got $($signature.SignerCertificate.Thumbprint)"
}

Write-Host "Verified Authenticode signature for $($artifact.Path) ($($signature.SignerCertificate.Thumbprint))"
