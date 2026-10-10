# Security

## Reporting a problem

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting on this repository instead. Include steps to reproduce if you can.

## Secrets

Trueup reads `NEATLOGS_API_KEY` and `TRUEUP_MODEL_KEY` from the environment. It should never print, log or store their values. If you find a place where it does, please report it as above.

Keep keys in a local `.env` file; it is listed in `.gitignore`.
