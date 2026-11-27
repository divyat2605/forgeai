# Groundability audit

Coverage score: **92%** (supported = 1, partial = 0.5). Verdicts were cross-checked: 0 model verdict(s) were overridden by the deterministic checks.

| Topic | Verdict | Evidence (verified quote) | Missing |
|---|---|---|---|
| passwords | supported | All user passwords expire every 180 days. `password-and-mfa-standard#3` | - |
| multi-factor authentication | partial | Multi-Factor Authentication (MFA) is mandatory for access to email, VPN and the HR portal. `password-and-mfa-standard#4` | The documents do not provide detailed steps on how to set up MFA, nor do they explain the specific t |
| vpn and remote access | supported | Access to the Virtual Private Network (VPN) is restricted to specific categories of staff  `remote-access-and-vpn#2` | - |
| company laptops and phones | supported | Lost or stolen devices must be reported within 24 hours to the Service Desk. `devices-and-software#6` | - |
| software requests | supported | All software requests go through the IT portal. This centralized system allows for trackin `devices-and-software#8` | - |
| password reset | supported | After 5 failed sign-in attempts the account locks for 30 minutes. `password-and-mfa-standard#6` | - |
