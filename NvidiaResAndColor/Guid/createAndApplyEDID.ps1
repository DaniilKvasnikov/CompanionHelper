###############################################################################
# createAndApplyEDID.ps1
#
# SYNOPSIS: Generates a custom EDID with the specified resolution and refresh
#           rate, saves it as a text file, then applies it via NVWMI fakeEDID.
#
# PARAMETERS:
#   -Width       Horizontal resolution in pixels      (default: 1920)
#   -Height      Vertical resolution in pixels         (default: 1080)
#   -RefreshRate Refresh rate in Hz / fps              (default: 60)
#   -OutputType  GPU output connector type:
#                  1=VGA  2=Component  3=S-Video  4=HDMI  5=DVI
#                  6=LVDS  7=DP  8=Composite  9=All    (default: 7=DP)
#   -PortIndex   Port index on the GPU.
#                  -1  = apply to all ports of OutputType (fakeEDID)
#                  >=0 = apply to a specific port       (fakeEDIDOnPort)
#                  (default: -1)
#   -Computer    Target machine name or IP              (default: localhost)
#   -EdidFile    Path to save the generated EDID text file.
#                Defaults to %ProgramData%\CustomEDID_WxH@fps.txt
#
# USAGE EXAMPLES:
#   .\createAndApplyEDID.ps1
#   .\createAndApplyEDID.ps1 -Width 2560 -Height 1440 -RefreshRate 144
#   .\createAndApplyEDID.ps1 -Width 1920 -Height 1080 -RefreshRate 120 -OutputType 4 -PortIndex 0
#   .\createAndApplyEDID.ps1 -Width 3840 -Height 2160 -RefreshRate 30  -Computer "192.168.1.10"
#
# NOTES:
#   Requires NVIDIA WMI Provider installed and administrator privileges.
#   EDID timing parameters are calculated using CEA-861 proportional blanking
#   scaled from the 1920x1080 reference timing (H_blank=280, V_blank=45).
#
###############################################################################

param(
    [int]    $Width       = 1920,
    [int]    $Height      = 1080,
    [int]    $RefreshRate = 60,
    [int]    $OutputType  = 7,
    [int]    $PortIndex   = -1,
    [string] $Computer    = "localhost",
    [string] $EdidFile    = ""
)

$namespace = "root\CIMV2\NV"

# Output type names for display purposes
$outputNames = @("", "VGA", "Component", "S-Video", "HDMI", "DVI", "LVDS", "DP", "Composite", "All")

# =============================================================================
# Timing calculation
# Blanking scaled proportionally from the 1080p CEA-861 reference:
#   H_blank = 280 px  (H_total = 2200),  V_blank = 45 lines (V_total = 1125)
# =============================================================================
function Get-Timings {
    param([int]$W, [int]$H, [int]$FPS)

    # Horizontal blanking: scale from ref, keep multiple of 8 (char cell)
    $hBlank = [int]([Math]::Round($W * 280.0 / 1920 / 8) * 8)
    if ($hBlank -lt 80) { $hBlank = 80 }

    # Vertical blanking: scale from ref, min 18 lines
    $vBlank = [int]([Math]::Round($H * 45.0 / 1080))
    if ($vBlank -lt 18) { $vBlank = 18 }

    # Sync parameters scaled from 1080p CEA reference:
    #   H: offset=88 px, width=44 px
    #   V: offset=4 lines, width=5 lines
    $hSyncOff = [int]([Math]::Round($W * 88.0 / 1920 / 8) * 8)
    if ($hSyncOff -lt 8) { $hSyncOff = 8 }

    $hSyncW = [int]([Math]::Round($W * 44.0 / 1920 / 8) * 8)
    if ($hSyncW -lt 8) { $hSyncW = 8 }

    $vSyncOff = [Math]::Max(1, [int]([Math]::Round($H * 4.0 / 1080)))
    $vSyncW   = [Math]::Max(1, [int]([Math]::Round($H * 5.0 / 1080)))

    # Pixel clock in units of 10 kHz (as stored in EDID DTD)
    $pclk10k = [int](($W + $hBlank) * ($H + $vBlank) * $FPS / 10000)

    return @{
        HActive     = $W
        HBlanking   = $hBlank
        HSyncOffset = $hSyncOff
        HSyncWidth  = $hSyncW
        VActive     = $H
        VBlanking   = $vBlank
        VSyncOffset = $vSyncOff
        VSyncWidth  = $vSyncW
        PixClk10kHz = $pclk10k
    }
}

# =============================================================================
# EDID binary construction (128-byte base EDID v1.4)
# =============================================================================
function Build-Edid {
    param([int]$W, [int]$H, [int]$FPS)

    $t    = Get-Timings -W $W -H $H -FPS $FPS
    $edid = [byte[]]::new(128)

    # ── Header ────────────────────────────────────────────────────────────────
    $edid[0] = 0x00
    $edid[1] = 0xFF; $edid[2] = 0xFF; $edid[3] = 0xFF
    $edid[4] = 0xFF; $edid[5] = 0xFF; $edid[6] = 0xFF
    $edid[7] = 0x00

    # ── Vendor / Product ──────────────────────────────────────────────────────
    # Manufacturer ID "NVD": N=14, V=22, D=4
    # Packed as 0|01110|10110|00100 = 0x3A 0xC4 (big-endian)
    $edid[8]  = 0x3A
    $edid[9]  = 0xC4
    $edid[10] = 0x00; $edid[11] = 0x00   # Product code
    $edid[12] = 0x00; $edid[13] = 0x00   # Serial number
    $edid[14] = 0x00; $edid[15] = 0x00

    # ── Version ───────────────────────────────────────────────────────────────
    $edid[16] = 0x01   # Week of manufacture
    $edid[17] = 0x1E   # Year: 1990 + 30 = 2020
    $edid[18] = 0x01   # EDID version 1
    $edid[19] = 0x04   # EDID revision 4

    # ── Basic display parameters ──────────────────────────────────────────────
    # Byte 20: digital input | 8 bpc (010) | DisplayPort (101) = 0xA5
    $edid[20] = 0xA5
    $edid[21] = 0x00   # H image size (undefined)
    $edid[22] = 0x00   # V image size (undefined)
    $edid[23] = 0x78   # Gamma 2.2: (2.2 - 1) * 100 = 120 = 0x78
    $edid[24] = 0x06   # Feature support: preferred timing in first DTD, sRGB

    # ── Chromaticity (standard sRGB primaries) ────────────────────────────────
    $edid[25] = 0xEE; $edid[26] = 0x91
    $edid[27] = 0xA3; $edid[28] = 0x54
    $edid[29] = 0x4C; $edid[30] = 0x99
    $edid[31] = 0x26; $edid[32] = 0x0F
    $edid[33] = 0x50; $edid[34] = 0x54

    # ── Established / Standard timings (none — DTD carries everything) ─────────
    $edid[35] = 0x00; $edid[36] = 0x00; $edid[37] = 0x00
    for ($i = 38; $i -le 53; $i += 2) {
        $edid[$i] = 0x01; $edid[$i + 1] = 0x01   # unused: 0x0101
    }

    # ── Descriptor 1 (offset 54-71): Detailed Timing Descriptor (DTD) ─────────
    $pc  = $t.PixClk10kHz
    $edid[54] = [byte]($pc -band 0xFF)
    $edid[55] = [byte](($pc -shr 8) -band 0xFF)

    $ha = $t.HActive;    $hb = $t.HBlanking
    $edid[56] = [byte]($ha -band 0xFF)
    $edid[57] = [byte]($hb -band 0xFF)
    $edid[58] = [byte](((($ha -shr 8) -band 0x0F) -shl 4) -bor (($hb -shr 8) -band 0x0F))

    $va = $t.VActive;    $vb = $t.VBlanking
    $edid[59] = [byte]($va -band 0xFF)
    $edid[60] = [byte]($vb -band 0xFF)
    $edid[61] = [byte](((($va -shr 8) -band 0x0F) -shl 4) -bor (($vb -shr 8) -band 0x0F))

    $hso = $t.HSyncOffset; $hsw = $t.HSyncWidth
    $vso = $t.VSyncOffset; $vsw = $t.VSyncWidth
    $edid[62] = [byte]($hso -band 0xFF)
    $edid[63] = [byte]($hsw -band 0xFF)
    $edid[64] = [byte]((($vso -band 0x0F) -shl 4) -bor ($vsw -band 0x0F))
    # Upper bits of H/V sync offsets and widths (all zero for typical values)
    $edid[65] = [byte](
        ((($hso -shr 8) -band 0x03) -shl 6) -bor
        ((($hsw -shr 8) -band 0x03) -shl 4) -bor
        ((($vso -shr 4) -band 0x03) -shl 2) -bor
         (($vsw -shr 4) -band 0x03)
    )

    # Image size: 527 mm x 296 mm (approx. 24" 16:9)
    $edid[66] = [byte](527 -band 0xFF)
    $edid[67] = [byte](296 -band 0xFF)
    $edid[68] = [byte](((527 -shr 8 -band 0x0F) -shl 4) -bor (296 -shr 8 -band 0x0F))

    $edid[69] = 0x00   # H border
    $edid[70] = 0x00   # V border
    # Flags: non-interlaced, separate sync, H+/V+ polarity
    $edid[71] = 0x18

    # ── Descriptor 2 (offset 72-89): Monitor Name ─────────────────────────────
    $edid[72] = 0x00; $edid[73] = 0x00; $edid[74] = 0x00
    $edid[75] = 0xFC   # Tag: monitor name
    $edid[76] = 0x00
    $name      = "{0}x{1}@{2}Hz" -f $W, $H, $FPS
    if ($name.Length -gt 13) { $name = $name.Substring(0, 13) }
    $nameBytes = [System.Text.Encoding]::ASCII.GetBytes($name)
    for ($i = 0; $i -lt 13; $i++) {
        if ($i -lt $nameBytes.Length) {
            $edid[77 + $i] = $nameBytes[$i]
        } elseif ($i -eq $nameBytes.Length) {
            $edid[77 + $i] = 0x0A   # string terminator
        } else {
            $edid[77 + $i] = 0x20   # padding
        }
    }

    # ── Descriptor 3 (offset 90-107): Monitor Range Limits ────────────────────
    $edid[90] = 0x00; $edid[91] = 0x00; $edid[92] = 0x00
    $edid[93] = 0xFD   # Tag: range limits
    $edid[94] = 0x00   # Flags: no offsets
    $edid[95] = 0x01   # V min (Hz)
    $edid[96] = [byte]([Math]::Min($FPS + 5, 255))   # V max (Hz)
    $edid[97] = 0x01   # H min (kHz)
    $edid[98] = 0xFF   # H max (kHz)
    # Max pixel clock: ceil(MHz / 10), each unit = 10 MHz
    $maxPclkField = [byte]([Math]::Max(1, [Math]::Ceiling($t.PixClk10kHz / 1000.0)))
    $edid[99]  = $maxPclkField
    $edid[100] = 0x00   # No secondary timing
    $edid[101] = 0x0A   # Padding
    $edid[102] = 0x20; $edid[103] = 0x20; $edid[104] = 0x20
    $edid[105] = 0x20; $edid[106] = 0x20; $edid[107] = 0x20

    # ── Descriptor 4 (offset 108-125): Unused ─────────────────────────────────
    $edid[108] = 0x00; $edid[109] = 0x00; $edid[110] = 0x00
    $edid[111] = 0x10   # Tag: dummy / unused
    for ($i = 112; $i -le 125; $i++) { $edid[$i] = 0x00 }

    # ── Extension count ────────────────────────────────────────────────────────
    $edid[126] = 0x00

    # ── Checksum ───────────────────────────────────────────────────────────────
    $sum = 0
    for ($i = 0; $i -lt 127; $i++) { $sum += $edid[$i] }
    $edid[127] = [byte]((256 - ($sum % 256)) % 256)

    return $edid
}

# =============================================================================
# Save EDID bytes as hex text file (NVWMI text format: hex pairs, 16/line)
# =============================================================================
function Save-EdidToTextFile {
    param([byte[]]$Bytes, [string]$Path)

    $lines = @()
    for ($i = 0; $i -lt $Bytes.Length; $i += 16) {
        $end  = [Math]::Min($i + 15, $Bytes.Length - 1)
        $line = ($Bytes[$i..$end] | ForEach-Object { "{0:X2}" -f $_ }) -join " "
        $lines += $line
    }
    [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.Encoding]::ASCII)
}

# =============================================================================
# Main
# =============================================================================

# Validate parameters
if ($Width  -lt 320  -or $Width  -gt 7680) { "FAILURE : Width out of range (320-7680)";  return }
if ($Height -lt 240  -or $Height -gt 4320) { "FAILURE : Height out of range (240-4320)"; return }
if ($RefreshRate -lt 1 -or $RefreshRate -gt 240) { "FAILURE : RefreshRate out of range (1-240)"; return }
if ($OutputType -lt 1 -or $OutputType -gt 9) { "FAILURE : OutputType must be 1-9"; return }

# Determine EDID file path
if ([string]::IsNullOrEmpty($EdidFile)) {
    $EdidFile = Join-Path -Path ${env:ProgramData} -ChildPath ("CustomEDID_{0}x{1}@{2}Hz.txt" -f $Width, $Height, $RefreshRate)
}

# ── Generate EDID ──────────────────────────────────────────────────────────────
"=== Generating EDID ==="
"  Resolution   : {0} x {1}" -f $Width, $Height
"  Refresh rate : {0} Hz" -f $RefreshRate

$edidBytes = Build-Edid -W $Width -H $Height -FPS $RefreshRate
$t         = Get-Timings -W $Width -H $Height -FPS $RefreshRate

$pclkMHz = [Math]::Round($t.PixClk10kHz * 10.0 / 1000, 3)
"  Pixel clock  : {0} MHz" -f $pclkMHz
"  H total      : {0}  ({1} active + {2} blank)" -f ($Width  + $t.HBlanking), $Width,  $t.HBlanking
"  V total      : {0}  ({1} active + {2} blank)" -f ($Height + $t.VBlanking), $Height, $t.VBlanking
"  H sync       : offset = {0}, width = {1}" -f $t.HSyncOffset, $t.HSyncWidth
"  V sync       : offset = {0}, width = {1}" -f $t.VSyncOffset, $t.VSyncWidth
""

# Verify checksum
$sum = 0
foreach ($b in $edidBytes) { $sum += $b }
if ($sum % 256 -ne 0) {
    "FAILURE : EDID checksum error (sum = {0})" -f $sum
    return
}

# Save EDID text file
Save-EdidToTextFile -Bytes $edidBytes -Path $EdidFile
if (Test-Path -Path $EdidFile) {
    "SUCCESS : EDID saved to $EdidFile"
} else {
    "FAILURE : could not write EDID file to $EdidFile"
    return
}

# ── Apply via NVWMI ────────────────────────────────────────────────────────────
""
"=== Applying EDID via NVWMI ==="
"  Computer     : $Computer"
"  Output type  : {0} ({1})" -f $OutputType, $outputNames[$OutputType]
"  Port index   : {0}" -f $(if ($PortIndex -lt 0) { "all" } else { $PortIndex })
""

$gpus = Get-WmiObject -class Gpu -computername $Computer -namespace $namespace
if ($gpus -eq $null) {
    "FAILURE : no GPUs found on $Computer"
    return
}

foreach ($gpu in $gpus) {
    "Processing GPU : " + $gpu.uname

    if ($PortIndex -lt 0) {
        # Apply to all ports of the given output type
        $params          = $gpu.GetMethodParameters("fakeEDID")
        $params.filePath = $EdidFile
        $params.output   = $OutputType
        $res             = $gpu.InvokeMethod("fakeEDID", $params, $null)
        if ($res.ReturnValue -eq $true) {
            "  SUCCESS : EDID applied on all {0} ports" -f $outputNames[$OutputType]
        } else {
            "  FAILURE : fakeEDID returned false"
        }
    } else {
        # Apply to a specific port
        $params            = $gpu.GetMethodParameters("fakeEDIDOnPort")
        $params.filePath   = $EdidFile
        $params.output     = $OutputType
        $params.portIndex  = $PortIndex
        $res               = $gpu.InvokeMethod("fakeEDIDOnPort", $params, $null)
        if ($res.ReturnValue -eq $true) {
            "  SUCCESS : EDID applied on {0} port {1}" -f $outputNames[$OutputType], $PortIndex
        } else {
            "  FAILURE : fakeEDIDOnPort returned false"
        }
    }
}
