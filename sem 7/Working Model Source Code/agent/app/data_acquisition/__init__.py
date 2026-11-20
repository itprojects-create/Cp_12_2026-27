"""Official-data acquisition framework (data-acquisition master prompt, Phase A).

Raw-first, content-addressed, manifest-per-run. No CAPTCHA/auth/paywall/bot
bypass, no stealth scraping (§4): blocked sources return SOURCE_BLOCKED and
are logged. No strategy logic here (§65): acquisition → validation → registry.
"""
