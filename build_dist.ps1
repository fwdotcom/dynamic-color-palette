# Build distribution ZIPs for itch.io release.
#
# Output:
#   dist/zip/dynamic_color_palette.zip                  -- Blender addon (flat, __pycache__ excluded)
#   dist/zip/dynamic_color_palette_godot_shader.zip     -- Godot 4 shader

$Root   = $PSScriptRoot
$Dist   = Join-Path $Root "dist\zip"

function Build-Zip {
    param(
        [string]$Label,
        [string]$SrcDir,
        [string]$OutFile,
        [string[]]$Exclude = @()
    )

    if (Test-Path $OutFile) { Remove-Item $OutFile }

    $files = Get-ChildItem -Path $SrcDir -Recurse -File |
        Where-Object {
            $rel = $_.FullName.Substring($SrcDir.Length + 1)
            # drop __pycache__ and .pyc
            $rel -notmatch '(^|\\)__pycache__(\\|$)' -and
            $_.Extension -ne '.pyc'
        }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::Open($OutFile, 'Create')

    foreach ($file in $files) {
        $arcName = $file.FullName.Substring($SrcDir.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file.FullName, $arcName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }

    $zip.Dispose()

    $sizeKB = [math]::Round((Get-Item $OutFile).Length / 1KB)
    Write-Host "  $Label  ($sizeKB KB)"
    $zip2 = [System.IO.Compression.ZipFile]::OpenRead($OutFile)
    $zip2.Entries | ForEach-Object { Write-Host "    $($_.FullName)" }
    $zip2.Dispose()
}

New-Item -ItemType Directory -Force -Path $Dist | Out-Null
Write-Host "`nBuilding dist ZIPs...`n"

Build-Zip `
    -Label  "dist\zip\dynamic_color_palette.zip" `
    -SrcDir (Join-Path $Root "dynamic_color_palette") `
    -OutFile (Join-Path $Dist "dynamic_color_palette.zip")

Write-Host ""

Build-Zip `
    -Label  "dist\zip\dynamic_color_palette_godot_shader.zip" `
    -SrcDir (Join-Path $Root "godot_4_shader") `
    -OutFile (Join-Path $Dist "dynamic_color_palette_godot_shader.zip")

Write-Host "`nDone."
