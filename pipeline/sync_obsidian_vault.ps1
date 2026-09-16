# vault/ (파이프라인 실제 출력) -> vault_obsidian/ (사람 검수용, artworks 제외) 증분 동기화.
# robocopy는 기본적으로 크기/수정시각이 다른 파일만 복사하므로, 재실행 비용은
# "새로 추가/변경된 문서 수"에 비례한다 — 전체 재복사가 아니다.
# artworks(265만 건)는 Obsidian 성능 문제로 의도적으로 제외 (2026-09-09).
$folders = @('artists', 'museums', 'galleries', 'auctions', 'collectors')
$src = 'C:\Users\CNCITY\artrend\vault'
$dst = 'C:\Users\CNCITY\artrend\vault_obsidian'

foreach ($f in $folders) {
    Write-Host "syncing $f ..."
    robocopy "$src\$f" "$dst\$f" /E /NFL /NDL /NJH /NC /NP
}

Write-Host "syncing root dashboard ..."
Copy-Item "$src\00 대시보드.md" "$dst\00 대시보드.md" -Force

Write-Host "done"
