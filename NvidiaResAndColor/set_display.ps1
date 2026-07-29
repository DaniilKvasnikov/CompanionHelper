param (
    [int]$width = 3840,
    [int]$height = 2160,
    [int]$freq = 48
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$codeDisplay = @"
using System;
using System.Runtime.InteropServices;
namespace DisplayConfig {
    [StructLayout(LayoutKind.Sequential)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion; public short dmDriverVersion; public short dmSize;
        public short dmDriverExtra; public int dmFields; public int dmPositionX;
        public int dmPositionY; public int dmDisplayOrientation; public int dmDisplayFixedOutput;
        public short dmColor; public short dmDuplex; public short dmYResolution;
        public short dmTTOption; public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels; public short dmBitsPerPel; public int dmPelsWidth;
        public int dmPelsHeight; public int dmDisplayFlags; public int dmDisplayFrequency;
    }
    public class Setter {
        [DllImport("user32.dll")] public static extern int EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);
        [DllImport("user32.dll")] public static extern int ChangeDisplaySettings(ref DEVMODE devMode, int flags);
        public static int SetRes(int width, int height, int freq) {
            DEVMODE dm = new DEVMODE();
            dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
            if (0 == EnumDisplaySettings(null, -1, ref dm)) { return -1; }
            dm.dmPelsWidth = width; dm.dmPelsHeight = height; dm.dmDisplayFrequency = freq;
            dm.dmFields = 0x80000 | 0x100000 | 0x400000;
            int res = ChangeDisplaySettings(ref dm, 0);
            if (res != 0) { Console.WriteLine("Error: " + width + "x" + height + "@" + freq + "Hz not supported."); }
            return res;
        }
    }
}
"@

Add-Type -TypeDefinition $codeDisplay -ErrorAction SilentlyContinue

Write-Host "Setting resolution to $($width)x$($height) @ $($freq)Hz..." -ForegroundColor Cyan
$resResult = [DisplayConfig.Setter]::SetRes($width, $height, $freq)
if ($resResult -ne 0) {
    Write-Host "Failed to set resolution $($width)x$($height)@$($freq)Hz (code $resResult)" -ForegroundColor Red
    exit 1
}

$exePath = "$env:USERPROFILE\Documents\configureSync_amd64\configureSync.exe"
if (Test-Path $exePath) {
    Write-Host "Starting sync..." -ForegroundColor Green
    & $exePath enable client display=0,0
} else {
    Write-Host "File not found: $exePath" -ForegroundColor Red
}

exit 0
