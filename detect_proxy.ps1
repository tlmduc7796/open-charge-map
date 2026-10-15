$ErrorActionPreference = 'SilentlyContinue'
$candidates = [System.Collections.Generic.List[string]]::new()

foreach ($name in @('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy','ALL_PROXY','all_proxy')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) { $candidates.Add($value) }
}

function Add-ProxyServer([string]$value) {
    if (-not $value) { return }
    foreach ($part in $value.Split(';')) {
        $entry = $part.Trim()
        if ($entry -match '^(?:https?|http|socks)=([^=]+)$') { $entry = $Matches[1].Trim() }
        if ($entry -match '^[^:/]+:d+$' -or $entry -match '^https?://') {
            if ($entry -notmatch '^https?://') { $entry = "http://$entry" }
            $candidates.Add($entry)
        }
    }
}

$internetSettings = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
if ($internetSettings.ProxyEnable -eq 1) { Add-ProxyServer $internetSettings.ProxyServer }

$winHttp = (& netsh winhttp show proxy 2>$null | Out-String)
if ($winHttp -match '(?im)Proxy Server(?:\(s\))?\s*:\s*([^\r\n]+)') {
    Add-ProxyServer $Matches[1].Trim()
}

foreach ($candidate in ($candidates | Select-Object -Unique)) {
    try {
        $uri = [Uri]$candidate
        if ($uri.Scheme -notin @('http','https') -or -not $uri.Host -or $uri.Port -le 0) { continue }

        $request = [System.Net.HttpWebRequest]::Create('https://rsapi.goong.io/Direction')
        $request.Proxy = [System.Net.WebProxy]::new($uri)
        $request.Timeout = 3500
        $request.ReadWriteTimeout = 3500
        $request.Method = 'GET'
        try {
            $response = $request.GetResponse()
            $response.Close()
            [Console]::WriteLine($uri.AbsoluteUri.TrimEnd('/'))
            exit 0
        } catch [System.Net.WebException] {
            if ($_.Exception.Response) {
                $_.Exception.Response.Close()
                [Console]::WriteLine($uri.AbsoluteUri.TrimEnd('/'))
                exit 0
            }
        }
    } catch {}
}
exit 0