[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$Text
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$speaker = $null
$tokens = $null
$format = $null
$stream = $null
$selected = $null

try {
    $target = [System.IO.Path]::GetFullPath($OutputPath)
    $directory = [System.IO.Path]::GetDirectoryName($target)
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null

    $speaker = New-Object -ComObject SAPI.SpVoice
    $tokens = $speaker.GetVoices()
    for ($index = 0; $index -lt $tokens.Count; $index++) {
        $candidate = $tokens.Item($index)
        $description = [string]$candidate.GetDescription()
        $language = [string]$candidate.GetAttribute("Language")
        if ($language -match "(?i)(^|;)804($|;)" -or $description -match "(?i)(Chinese|Mandarin|Huihui|Xiaoxiao)") {
            $selected = $candidate
            break
        }
    }
    if ($null -eq $selected) {
        throw "No Chinese Windows SAPI voice is installed."
    }

    $speaker.Voice = $selected
    $speaker.Rate = 0
    $speaker.Volume = 100

    $format = New-Object -ComObject SAPI.SpAudioFormat
    # SAFT16kHz16BitMono. Faster-Whisper receives only the PCM frames.
    $format.Type = 18
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Format = $format
    # SSFMCreateForWrite
    $stream.Open($target, 3, $false)
    $speaker.AudioOutputStream = $stream
    $null = $speaker.Speak($Text)
    $stream.Close()
    $stream = $null

    [ordered]@{
        ok = $true
        voice = [string]$selected.GetDescription()
        text = $Text
        format = "pcm_s16le_16000_mono"
    } | ConvertTo-Json -Compress
}
finally {
    if ($null -ne $stream) {
        try { $stream.Close() } catch { }
    }
    foreach ($comObject in @($stream, $format, $tokens, $speaker)) {
        if ($null -ne $comObject -and [System.Runtime.InteropServices.Marshal]::IsComObject($comObject)) {
            $null = [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($comObject)
        }
    }
}
