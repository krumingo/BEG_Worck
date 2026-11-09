import re, subprocess, sys, collections
PAT = {
 "stripe_live": r"sk_live_[0-9A-Za-z]{10,}", "stripe_test": r"sk_test_[0-9A-Za-z]{10,}", "stripe_rk": r"rk_(live|test)_[0-9A-Za-z]{10,}",
 "stripe_whsec": r"whsec_[0-9A-Za-z]{10,}", "emergent_key": r"sk-emergent-[0-9A-Za-z]{6,}", "openai": r"sk-(proj-)?[A-Za-z0-9_-]{20,}",
 "anthropic": r"sk-ant-[A-Za-z0-9_-]{20,}", "aws_akid": r"AKIA[0-9A-Z]{16}", "google_api": r"AIza[0-9A-Za-z_-]{35}",
 "github": r"gh[pousr]_[A-Za-z0-9]{30,}", "slack": r"xox[baprs]-[A-Za-z0-9-]{10,}", "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
 "mongo_uri_creds": r"mongodb(\+srv)?://[^:\s/\"']+:[^@\s\"']+@[^\s\"'/]+", "jwt": r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
 "posthog": r"phc_[A-Za-z0-9]{20,}", "sendgrid": r"SG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
 "assign_secret": r"(?i)(JWT_SECRET|SECRET_KEY|PASSWORD|API_KEY|TOKEN|SMTP_PASS\w*|BOOTSTRAP_TOKEN)\s*[=:]\s*[\"']?([^\s\"'#]{8,})",
}
log = subprocess.run(["git","log","--all","-p","--no-color","--format=@@COMMIT %h %ad","--date=short","-U0"],capture_output=True,text=True,errors="replace").stdout
found = collections.OrderedDict()
commit=None; f=None
for line in log.splitlines():
    if line.startswith("@@COMMIT "): commit=line.split()[1]+" "+line.split()[2]; continue
    if line.startswith("+++ b/"): f=line[6:]; continue
    if not line.startswith("+") or line.startswith("+++"): continue
    for name,p in PAT.items():
        for m in re.finditer(p,line):
            val = m.group(2) if name=="assign_secret" else m.group(0)
            if name=="assign_secret" and (re.search(r"(os\.environ|getenv|\$\{|<|your|example|changeme|placeholder|xxx|\*\*\*|REDACTED|test|dummy|fake|probe|secret|None|process\.env|\.get\(|password_hash|\(|\)|\[)",val,re.I) ): continue
            key=(name,val)
            found.setdefault(key,[]).append((commit,f))
for (name,val),locs in found.items():
    first=locs[0]; mask=("…"+val[-4:]) if len(val)>4 else "…"
    files=sorted(set(l[1] for l in locs))
    print(f"{name}\t{mask}\tfirst={first[0]}\tcommits={len(set(l[0] for l in locs))}\tfiles={files[:3]}{'+' if len(files)>3 else ''}")
