# Internal IT Standard: Password and Multi-Factor Authentication

## Scope

This standard establishes the mandatory requirements for user authentication across all corporate systems. It applies to every employee, contractor, and third-party vendor with access to company resources. Adherence is required to maintain the integrity of our data infrastructure and protect against unauthorized access. Non-compliance may result in restricted system access or disciplinary action.

## Password Rules

To ensure robust protection against brute-force and dictionary attacks, all user passwords must meet specific complexity and uniqueness criteria. Every password must be a minimum of 14 characters in length. Shorter passwords are rejected by the system during creation or modification.

Users are strictly prohibited from reusing recent passwords to prevent cycle-based guessing. The system enforces a history check that prevents the reuse of the last 5 passwords. If a user attempts to set a password identical to one used within that window, the system will reject the change and prompt for a new value. Passwords must not contain obvious personal information or common dictionary words.

## Password Expiry

Regular rotation of credentials is required to limit the window of opportunity for attackers who may have obtained a password through phishing or data breaches. All user passwords expire every 180 days. When a password reaches its expiration date, the user will be forced to change it before accessing any corporate resource.

To ensure users are prepared for this requirement and can plan their updates accordingly, the system initiates a warning period 14 days before expiry. During this window, users will see persistent notifications on their login screens and in their email alerts reminding them of the impending deadline. Users are encouraged to update their passwords immediately upon receiving these warnings to avoid service interruption.

## Multi-Factor Authentication (MFA)

Single-factor authentication is no longer sufficient for securing sensitive corporate accounts. Multi-Factor Authentication (MFA) is mandatory for access to email, VPN and the HR portal. These systems will reject any login attempt that does not include a second form of verification.

The approved method for MFA is the Authenticator app. Users must configure their corporate accounts to use this application on their mobile devices. The Authenticator app generates time-based one-time passwords (TOTP) that sync with our identity provider, ensuring high security without reliance on external networks.

SMS codes are only a fallback option. They should be used exclusively if the user cannot access their device or the Authenticator app is malfunctioning. SMS-based verification is less secure due to potential SIM-swapping attacks and network interception risks. Users are strongly discouraged from relying on SMS for daily authentication. IT will monitor for excessive use of SMS fallbacks and may require users to reconfigure their MFA settings if abuse is detected.

## Account Lockout

To protect accounts from automated credential stuffing and brute-force attacks, an automatic lockout mechanism is in place. After 5 failed sign-in attempts the account locks for 30 minutes. During this period, no login attempts will be processed, regardless of whether the correct password is entered.

This lockout applies to all authentication methods, including MFA challenges. If a user suspects their account has been locked due to suspicious activity, they must not attempt to guess their password repeatedly. Repeated failures may extend the lockout duration or trigger a security review by the IT team. Users who are locked out should wait for the 30-minute period to elapse before attempting to log in again.

## Getting Help

Users who encounter difficulties with password resets, MFA configuration, or account lockouts should utilize the available support channels. For immediate assistance, users can perform a self-service password reset at the portal passwords.example.internal. This portal allows authorized users to verify their identity and set a new password without human intervention.

If the self-service option is unavailable due to system issues or if the user is unable to complete the verification process, they must contact the Service Desk on extension 4400. The Service Desk team can manually verify identity and assist with account recovery. Please have your employee ID ready when calling to expedite the support process.
