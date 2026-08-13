param(
    [Parameter(Mandatory = $true)]
    [string] $Owner,

    [Parameter(Mandatory = $true)]
    [string] $Reference
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = $PSScriptRoot

function Invoke-Bccli {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    & bccli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "bccli failed with exit code $LASTEXITCODE`: bccli $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $Reference -PathType Leaf)) {
    throw "Reference file not found: $Reference"
}

Push-Location $ProjectRoot
try {
    # Rebuild the aggregate from the current remote state of all eligible
    # non-archived repositories owned by the selected GitHub owner.
    Invoke-Bccli @(
        'app-json', 'retrieve',
        '--owner', $Owner,
        '--output', 'app-json.json',
        '--refresh'
    )

    # Standard report as JSON. Customization (50000..99999) is removed from
    # the complete comparison domain, including conflicts and outside reference.
    Invoke-Bccli @(
        'object-ranges', 'report',
        '--app-json', 'app-json.json',
        '--reference', $Reference,
        '--output', 'object-range-report.json',
        '--output-format', 'json',
        '--ignore-range-type', 'customization'
    )

    # The same standard report as Markdown.
    Invoke-Bccli @(
        'object-ranges', 'report',
        '--app-json', 'app-json.json',
        '--reference', $Reference,
        '--output', 'object-range-report.md',
        '--output-format', 'markdown',
        '--ignore-range-type', 'customization'
    )

    # Additional filtered JSON examples.
    Invoke-Bccli @(
        'object-ranges', 'report',
        '--app-json', 'app-json.json',
        '--reference', $Reference,
        '--output', 'object-range-report-hide-rsp.json',
        '--output-format', 'json',
        '--hide-range-type', 'rsp'
    )

    Invoke-Bccli @(
        'object-ranges', 'report',
        '--app-json', 'app-json.json',
        '--reference', $Reference,
        '--output', 'object-range-report-ignore-rsp-app.json',
        '--output-format', 'json',
        '--ignore-range-type', 'rsp',
        '--ignore-range-type', 'app'
    )

    Invoke-Bccli @(
        'object-ranges', 'report',
        '--app-json', 'app-json.json',
        '--reference', $Reference,
        '--output', 'object-range-report-all-conflicts.json',
        '--output-format', 'json',
        '--conflict-range-type', 'base',
        '--conflict-range-type', 'customization',
        '--conflict-range-type', 'localization',
        '--conflict-range-type', 'rsp',
        '--conflict-range-type', 'app',
        '--conflict-range-type', 'unclassified'
    )

    # Verify that every expected output exists and that all JSON files parse.
    $Outputs = @(
        'app-json.json',
        'object-range-report.json',
        'object-range-report.md',
        'object-range-report-hide-rsp.json',
        'object-range-report-ignore-rsp-app.json',
        'object-range-report-all-conflicts.json'
    )

    foreach ($Output in $Outputs) {
        if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) {
            throw "Expected output was not created: $Output"
        }
    }

    Get-Content -LiteralPath 'app-json.json' -Raw | ConvertFrom-Json | Out-Null
    Get-Content -LiteralPath 'object-range-report.json' -Raw | ConvertFrom-Json | Out-Null
    Get-Content -LiteralPath 'object-range-report-hide-rsp.json' -Raw | ConvertFrom-Json | Out-Null
    Get-Content -LiteralPath 'object-range-report-ignore-rsp-app.json' -Raw | ConvertFrom-Json | Out-Null
    Get-Content -LiteralPath 'object-range-report-all-conflicts.json' -Raw | ConvertFrom-Json | Out-Null

    Write-Host 'All BCCLI output files were recreated and validated.'
    $Outputs | ForEach-Object { Write-Host "  $((Resolve-Path -LiteralPath $_).Path)" }
}
finally {
    Pop-Location
}
