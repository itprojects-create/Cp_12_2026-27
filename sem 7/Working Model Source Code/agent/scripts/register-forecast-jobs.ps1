# Register the Quant Plus forecast forward-clock scheduled jobs (Windows Task Scheduler).
# Prereq: backend runtime venv + INCEPTION_API_KEY in D:\QP\agent-service\.env.
# Times are local system time (IST): run after the 15:30 NSE close.
#
# Run once to (re)create the tasks. Check: schtasks /Query /TN <taskname> /XML
#
# NOTE: task names map to CLI verbs EXPLICITLY (a .Split() on a multi-char string in
# PowerShell splits per character and yielded an empty job verb once — do not parse).

$ErrorActionPreference = "Stop"

$python = "D:\Quant-Plus\.local-data\backend-runtime\Scripts\python.exe"
$workdir = "D:\QP\agent-service"
$logdir = "$workdir\data\forecast_reports"
New-Item -ItemType Directory -Force -Path $logdir | Out-Null

$jobs = @(
    @{ Name = "QPForecastSettle";     Job = "settle";     Time = "16:15" },
    @{ Name = "QPForecastDaily";      Job = "daily";      Time = "16:30" },
    @{ Name = "QPForecastTournament"; Job = "tournament"; Time = "17:30" },
    # Same-evening catch-up: re-runs the full chain (daily -> settle -> paper) after a
    # missed 16:15/16:30 run so no session's evidence is lost; every stage is idempotent.
    @{ Name = "QPForecastCatchup";    Job = "catchup";    Time = "21:00" }
)

foreach ($j in $jobs) {
    $argument = (
        "/c cd /d $workdir && `"$python`" -B -m quantplus_intelligence.forecast.jobs $($j.Job) " +
        ">> `"$logdir\schedule_$($j.Job).log`" 2>&1"
    )
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $argument
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $j.Time
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6)
    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output ("registered {0} -> {1} IST weekdays, job verb '{2}'" -f $j.Name, $j.Time, $j.Job)
}

Write-Output ""
Write-Output "Sanity: print each task's action line (job verb must appear):"
foreach ($j in $jobs) {
    $xml = schtasks /Query /TN $j.Name /XML
    ($xml | Select-String -SimpleMatch "forecast.jobs").Line.Trim()
}

Write-Output ""
Write-Output "Schedule notes:"
Write-Output "- Intraday veto: daily/tournament refuse to lock cards while the NSE session is live (audit AI-01)."
Write-Output "- Log tails: $logdir\schedule_<job>.log"
Write-Output "- Holidays: jobs run anyway; settle no-ops, daily reuses the last completed bar (no extra token spend)."
Write-Output "- Tasks use InteractiveToken: the PC must be logged on for them to fire (locked is fine)."
Write-Output "- QPForecastCatchup (21:00) chains daily -> settle -> paper in one process; result JSON lands in"
Write-Output "  $logdir\schedule_catchup.log, the paper stream in $logdir\paper_pnl.jsonl (+ paper_<date>.json)."
