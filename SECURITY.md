# Security and privacy

Do not post credentials, account details, model configuration files, backup files or OAuth URLs in GitHub issues. Error reports should include only a redacted message, application version, Windows/Python version and reproduction steps.

This project has no telemetry and records no prompt or response contents. It stores encrypted authorization data in the current Windows user's local data directory and binds only to the loopback interface. Other programs running as the same Windows user can still access user-controlled credentials; DPAPI is not isolation from compromised local software.

Report vulnerabilities privately through the repository's GitHub private vulnerability reporting feature if available. If unavailable, do not publish exploit details or sensitive data; contact the maintainer through a private channel. Issues affecting OpenAI user credentials should also be reported to OpenAI support.

Only personal, expressly authorized use in the connected MaiBot installation is supported. The project does not authorize account sharing, subscription resale or fulfilling another person's requests. It is not a general-purpose subscription API gateway.
