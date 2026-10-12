# 주간 갱신 잡 일괄 실행 (2026-09-17 docs/갱신잡_20260917.md 정리 후속, 메인 지시)
#
# docs/갱신잡_20260917.md에서 idempotent·경량으로 확인된 5개 잡을 순차 실행한다.
# 각 단계는 독립적으로 실패해도 다음 단계로 계속 진행하고(한 소스 장애가 다른 소스를
# 막지 않게), 전체 로그를 docs/logs/refresh_YYYYMMDD.log에 남긴다.
#
# 실제 스케줄(Windows 작업 스케줄러 등) 등록은 이 스크립트 밖의 결정 — 여기서는
# "실행하면 되는 단일 명령"만 제공한다.
#
# 사용법:
#   powershell -File pipeline/refresh_weekly.ps1
#
# 전제: pgportable(포트 5433)이 떠 있어야 함, pipeline/.env에 DATABASE_URL 설정.

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "docs\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("refresh_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

# pipeline/run.py는 os.environ["DATABASE_URL"]만 직접 확인하고(db.py처럼 .env 폴백이
# 없음) 없으면 조용히 dry-run으로 빠진다 — 이 스크립트가 실제 DB에 반영되도록 .env에서
# 읽어 프로세스 환경변수로 주입한다(하드코딩 금지 원칙 유지, 값은 파일에서만 옴).
if (-not $env:DATABASE_URL) {
    $envFile = Join-Path $repoRoot "pipeline\.env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
        if ($line) {
            $env:DATABASE_URL = ($line -split '=', 2)[1].Trim()
        }
    }
}

# pgportable 자동 기동(2026-09-17 사용자 결정: 작업 스케줄러 월 08:30 등록, PC만 켜져 있으면 실행).
# 포트 5433 응답이 없으면 postgres.exe를 띄우고 최대 60초 대기. 그래도 안 뜨면 로그 남기고 종료.
$pgExe = "C:\pgportable\pgsql\bin\postgres.exe"
$pgData = "C:\pgportable\data"
function Test-Pg { try { (Test-NetConnection -ComputerName 127.0.0.1 -Port 5433 -WarningAction SilentlyContinue -InformationLevel Quiet) } catch { $false } }
if (-not (Test-Pg)) {
    Add-Content -Path $logFile -Encoding utf8 -Value "===== [$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] pgportable 미기동 → 기동 시도 ====="
    if (Test-Path $pgExe) {
        Start-Process -FilePath $pgExe -ArgumentList "-D", $pgData, "-p", "5433" -WindowStyle Hidden -RedirectStandardError (Join-Path $repoRoot "pipeline\_pg_server.log")
        $waited = 0
        while (-not (Test-Pg) -and $waited -lt 60) { Start-Sleep -Seconds 3; $waited += 3 }
    }
    if (-not (Test-Pg)) {
        Add-Content -Path $logFile -Encoding utf8 -Value "===== pgportable 기동 실패(60초) — 이번 주 갱신 건너뜀 ====="
        exit 2
    }
    Add-Content -Path $logFile -Encoding utf8 -Value "===== pgportable 기동 완료(${waited}s) ====="
}

function Run-Step {
    param(
        [string]$Name,
        [string]$WorkDir,
        [string[]]$Command
    )
    # Add-Content/Tee-Object가 PowerShell 5.1에서 기본 인코딩이 서로 달라(UTF-16LE vs
    # 콘솔 코드페이지) 섞어 쓰면 로그 파일이 깨진다 — 전부 -Encoding utf8로 통일.
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Encoding utf8 -Value "===== [$ts] $Name 시작 ====="
    Push-Location $WorkDir
    try {
        # PowerShell 5.1의 Tee-Object에는 -Encoding 파라미터가 없다(PS7+ 전용) — 캡처 후
        # Write-Host(콘솔)와 Out-File -Encoding utf8(로그) 둘로 나눠 인코딩을 통일한다.
        $output = & $Command[0] $Command[1..($Command.Length - 1)] 2>&1
        $exitCode = $LASTEXITCODE
        $output | ForEach-Object { Write-Host $_ }
        $output | Out-File -FilePath $logFile -Append -Encoding utf8
    } catch {
        Add-Content -Path $logFile -Encoding utf8 -Value "예외: $_"
        $exitCode = 1
    } finally {
        Pop-Location
    }
    $ts2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Encoding utf8 -Value "===== [$ts2] $Name 종료(exit $exitCode) ====="
    return $exitCode
}

$crawlersDir = Join-Path $repoRoot "crawlers"
$pipelineDir = Join-Path $repoRoot "pipeline"

# 1. Bonhams 증분
Run-Step -Name "Bonhams 크롤" -WorkDir $crawlersDir -Command @("python", "bonhams.py")
Run-Step -Name "Bonhams 적재" -WorkDir $pipelineDir -Command @("python", "run.py", "--site", "bonhams")

# 2. Wikidata 경매(auctions_wikidata)
Run-Step -Name "Wikidata 경매 크롤" -WorkDir $crawlersDir -Command @("python", "auctions.py", "--type", "all")
Run-Step -Name "Wikidata 경매 적재" -WorkDir $pipelineDir -Command @("python", "run.py", "--site", "auctions")

# 3. K-ARTMARKET 통계 (월 1회면 충분하지만 already_fetched가 같은 달 재실행을 스킵하므로
#    주간 스케줄에 얹어도 비용 없음 — kams_stats.py 자체 가드에 위임)
Run-Step -Name "K-ARTMARKET 크롤" -WorkDir $crawlersDir -Command @("python", "kams_stats.py")
Run-Step -Name "K-ARTMARKET 적재" -WorkDir $pipelineDir -Command @("python", "kams_stats_load.py", "--apply")

# 4. Wikidata 사건(수상/사망/전시) — QID 단위 재설계로 안정 상태 3~4초
Run-Step -Name "Wikidata 사건 크롤" -WorkDir $crawlersDir -Command @("python", "wikidata_artist_events.py")
Run-Step -Name "Wikidata 사건 적재" -WorkDir $pipelineDir -Command @("python", "wikidata_artist_events.py", "--apply")

# 5. 갤러리 5곳 전시 페이지(Gladstone/Lehmann Maupin/Taka Ishii/Pyo/Simon)
Run-Step -Name "갤러리 전시 크롤" -WorkDir $crawlersDir -Command @("python", "gallery_exhibitions_pages.py", "--site", "all")
Run-Step -Name "갤러리 전시 적재" -WorkDir $pipelineDir -Command @("python", "gallery_exhibitions_pages_load.py", "--site", "all", "--apply")

# 6. 건강지표 스냅샷(읽기 전용) — 갱신 전후 비교용
$healthDate = Get-Date -Format "yyyyMMdd"
$healthJson = Join-Path $logDir ("audit_health_{0}.json" -f $healthDate)
Run-Step -Name "건강지표 스냅샷" -WorkDir $pipelineDir -Command @("python", "audit_health.py", "--json", $healthJson)

Add-Content -Path $logFile -Encoding utf8 -Value "===== 전체 완료: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
Write-Host "완료 — 로그: $logFile"
