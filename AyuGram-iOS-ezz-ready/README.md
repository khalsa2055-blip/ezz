# AyuGram iOS — ezz workspace

هذا المستودع مخصص لبناء/التحقق من Port الخاص بـ AyuGram على Telegram-iOS باستخدام GitHub Actions (macOS).

## المحتويات

- `patches/ayugram-1.3.0.patch` — Patch الخاص بدمج AyuGram iOS.
- `.github/workflows/ayugram-verify.yml` — يتحقق من نسخة Telegram-iOS ويختبر قابلية تطبيق الـPatch.
- `.github/workflows/ayugram-build.yml` — Build اختياري على macOS بعد إضافة بيانات Telegram وApple.

## رفعه إلى GitHub

1. فك ضغط هذا الملف.
2. في المستودع `khalsa2055-blip/ezz` اختر **Add file → Upload files**.
3. ارفع المجلدين والملف `README.md` كما هما، ثم **Commit changes**.
4. افتح تبويب **Actions** وشغّل `AyuGram iOS — Verify Patch`.

> لا ترفع `api_hash` أو شهادات Apple أو ملفات provisioning إلى المستودع.

## بناء IPA

البناء الموقّع يحتاج Secrets في GitHub:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `APPLE_TEAM_ID`

كما يحتاج حساب Apple Developer وبيانات provisioning/codesigning المناسبة. الـWorkflow الموجود هنا يبدأ بـSimulator/verification ولا يدّعي إخراج IPA بدون هذه البيانات.

## المصدر الأساسي

Telegram-iOS: https://github.com/TelegramMessenger/Telegram-iOS

Baseline المستخدم في Workflow: commit `6ad963e5b62d354da79040f388ae2b9132fb17b8`، وهو الإصدار الذي يعلن `12.9.2` وXcode `26.2` في `versions.json`.

هذا مشروع غير رسمي؛ يجب أن يبقى واضحًا للمستخدمين أنه ليس تطبيق Telegram الرسمي، مع الالتزام بترخيص Telegram-iOS ومتطلبات توزيع أي مشتق منه.
