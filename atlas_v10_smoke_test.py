import os

os.environ.setdefault("ATLAS_SQLITE_FILE", "atlas_v103_smoke.sqlite3")
os.environ.setdefault("TELEGRAM_TOKEN", "TEST")

import bot

assert bot.VERSION == "ATLAS v10.3"
assert hasattr(bot, "ATLAS_PERSONAL_CRYPTO")
assert len(bot.ATLAS_PERSONAL_CRYPTO) >= 20
assert hasattr(bot, "personal_report")
assert hasattr(bot, "build_personal_report")
assert bot.PHYSICAL_ASSETS["GOLD"]["name"] == "طلا فیزیکی"
assert bot.PHYSICAL_ASSETS["SILVER"]["name"] == "نقره فیزیکی"
assert bot.PHYSICAL_ASSETS["COPPER"]["name"] == "مس فیزیکی"

print("ATLAS v10.3 smoke test: PASS")
print("Personal assets:", len(bot.ATLAS_PERSONAL_CRYPTO))
print("Physical assets: GOLD / SILVER / COPPER")
