$myProxy = [System.Environment]::GetEnvironmentVariable('MY_PROXY', 'User')

if ([string]::IsNullOrWhiteSpace($myProxy)) {
	Write-Error "MY_PROXY is missing. Stop setting HTTP_PROXY and HTTPS_PROXY."
	exit 1
}

$env:HTTP_PROXY = $myProxy
$env:HTTPS_PROXY = $myProxy

$machineNoProxy = [System.Environment]::GetEnvironmentVariable('NO_PROXY', 'User')
if (-not [string]::IsNullOrWhiteSpace($machineNoProxy)) {
	$env:NO_PROXY = $machineNoProxy
}

uv sync
