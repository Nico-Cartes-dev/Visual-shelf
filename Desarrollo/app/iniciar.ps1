$env:SUPABASE_URL = 'https://nkdcapusephxjtsvlhbj.supabase.co'
$env:SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_6KgkO_95F0ielIzZCVKbDw_8SbEHSVr'
Push-Location $PSScriptRoot
try { python app.py @args } finally { Pop-Location }
