$ErrorActionPreference = 'Stop'
$novaRoot = Split-Path $PSScriptRoot -Parent
$modelRoot = Join-Path $novaRoot 'backend\models'
& (Join-Path $novaRoot 'backend\.venv\Scripts\python.exe') -m pip install vosk==0.3.45
if ($LASTEXITCODE -ne 0) { throw 'Vosk installation failed' }
New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
$archive = Join-Path $modelRoot 'vosk-model-small-en-us-0.15.zip'
Invoke-WebRequest -UseBasicParsing 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' -OutFile $archive
Expand-Archive -LiteralPath $archive -DestinationPath $modelRoot -Force
