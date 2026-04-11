# Coverage Map

## Audit: 2026-04-10

### Files Analyzed
All 35 Python source files were assigned to at least one squad (100% coverage).

### CWE Categories Tested
CWE-22, CWE-78, CWE-200, CWE-209, CWE-269, CWE-276, CWE-295, CWE-306, CWE-311, CWE-312, CWE-316, CWE-319, CWE-353, CWE-362, CWE-367, CWE-400, CWE-426, CWE-460, CWE-477, CWE-502, CWE-532, CWE-706, CWE-754, CWE-770, CWE-778, CWE-1035, CWE-1068, CWE-1078, CWE-1104, CWE-1357, CWE-1395

### CWE Categories NOT Tested (from Top 25)
CWE-79 (XSS) — N/A, no web UI
CWE-89 (SQL Injection) — N/A, no database
CWE-94 (Code Injection) — No eval/exec patterns found
CWE-125/787 (Memory safety) — N/A, Python
CWE-434 (File Upload) — N/A, no file upload
CWE-611 (XXE) — N/A, no XML parsing
CWE-798 (Hardcoded Credentials) — Tested, none found
CWE-862/863 (Authorization) — N/A, no multi-user auth
CWE-918 (SSRF) — N/A, no user-controlled URLs in outbound requests

### Domains with Zero Findings
None — all deployed squads produced validated findings.

### Recommended Focus for Next Audit
- F-006 (GPL license) resolution should be verified
- F-012 (config dir ACLs) if implemented
- F-015 (launcher integrity) if implemented
- Regression testing on all HIGH fixes
