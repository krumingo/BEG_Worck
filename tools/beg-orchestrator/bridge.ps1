param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

function Audit([hashtable]$e,[string]$path) {
  $e.timestamp=(Get-Date).ToUniversalTime().ToString('o')
  $dir=Split-Path -Parent $path
  if($dir){New-Item -ItemType Directory -Force -Path $dir|Out-Null}
  ($e|ConvertTo-Json -Compress -Depth 8)|Add-Content -Encoding UTF8 -Path $path
}

function Load-State([string]$path) {
  if(Test-Path $path){
    try{return (Get-Content -Raw $path|ConvertFrom-Json -AsHashtable)}catch{}
  }
  return @{processed_comment_ids=@()}
}

function Save-State([hashtable]$s,[string]$path) {
  $dir=Split-Path -Parent $path
  if($dir){New-Item -ItemType Directory -Force -Path $dir|Out-Null}
  $s|ConvertTo-Json -Depth 8|Set-Content -Encoding UTF8 -Path $path
}

function Parse-Command([string]$body) {
  if(-not $body.StartsWith('BEG_BRIDGE_COMMAND')){return $null}
  $p=$body -split '(?m)^---\s*$',2
  if($p.Count -ne 2){return $null}
  $h=@{}
  foreach($line in ($p[0] -split '\r?\n')){
    if($line -match '^([A-Za-z_]+):\s*(.+?)\s*$'){$h[$matches[1]]=$matches[2]}
  }
  if(-not $h.ContainsKey('command_id')){return $null}
  if([string]$h['target'] -ne 'CODEX'){return $null}
  return @{command_id=$h['command_id'];prompt=$p[1].Trim()}
}

function Comments([string]$repo,[int]$issue) {
  $json=& gh api "repos/$repo/issues/$issue/comments" --paginate
  if($LASTEXITCODE -ne 0){throw 'gh api failed'}
  if(-not $json){return @()}
  return @($json|ConvertFrom-Json)
}

function Dispatch([string]$title,[string]$prompt) {
  $shell=New-Object -ComObject WScript.Shell
  if(-not $shell.AppActivate($title)){throw "Codex window not found: $title"}
  Start-Sleep -Milliseconds 500
  Set-Clipboard -Value $prompt
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
}

if(-not (Test-Path $Config)){throw "Config not found: $Config"}
$cfg=Get-Content -Raw $Config|ConvertFrom-Json -AsHashtable
& gh auth status|Out-Null
if($LASTEXITCODE -ne 0){throw 'GitHub CLI is not authenticated'}
$state=Load-State $cfg.state_file
$seen=[System.Collections.Generic.HashSet[string]]::new()
foreach($id in @($state.processed_comment_ids)){[void]$seen.Add([string]$id)}
Audit @{event='BRIDGE_STARTED';dry_run=[bool]$cfg.dry_run} $cfg.audit_file

while($true){
  try{
    foreach($c in (Comments $cfg.repository ([int]$cfg.issue_number))){
      $id=[string]$c.id
      if($seen.Contains($id)){continue}
      $cmd=Parse-Command ([string]$c.body)
      if($null -eq $cmd){[void]$seen.Add($id);continue}
      if([string]$c.user.login -ne [string]$cfg.trusted_github_login){
        Audit @{event='REJECTED';reason='UNTRUSTED_AUTHOR';comment_id=$id;command_id=$cmd.command_id} $cfg.audit_file
        [void]$seen.Add($id);continue
      }
      Audit @{event='ACCEPTED';comment_id=$id;command_id=$cmd.command_id;dry_run=[bool]$cfg.dry_run} $cfg.audit_file
      if(-not [bool]$cfg.dry_run){
        Dispatch ([string]$cfg.codex_window_title) ([string]$cmd.prompt)
        Audit @{event='DISPATCHED';comment_id=$id;command_id=$cmd.command_id} $cfg.audit_file
      }
      [void]$seen.Add($id)
      $state.processed_comment_ids=@($seen)
      Save-State $state $cfg.state_file
    }
  }catch{Audit @{event='ERROR';message=$_.Exception.Message} $cfg.audit_file}
  Start-Sleep -Seconds ([int]$cfg.poll_seconds)
}
