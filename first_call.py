import os
from pathlib import Path

# Read SARVAM_API_KEY from the environment; fall back to .env if not exported.
env_file = Path(__file__).with_name(".env")
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))

from sarvamai import SarvamAI
from sarvamai.play import save

client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])

audio = client.text_to_speech.convert(
    text="नमस्ते! मैं सर्वम एआई से बोल रहा हूँ।",
    language_code="hi-IN",
    model="bulbul:v4-flash",
    speaker="simran_en_customer",
)

out = Path(__file__).with_name("first_call.wav")
save(audio, str(out))
print(f"Saved audio to {out} ({out.stat().st_size:,} bytes)")
