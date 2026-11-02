import os
import sys
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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python voice_agent.py <audio-file>")
        raise SystemExit(1)

    input_path = Path(sys.argv[1])
    client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])

    # 1. Hear: Saaras transcribes the caller's speech.
    with input_path.open("rb") as f:
        stt = client.speech_to_text.transcribe(
            file=f,
            model="saaras:v4",
            mode="transcribe",
        )
    transcript = stt.transcript
    print(f"You said: {transcript}")

    # 2. Think: an LLM writes a short spoken-style reply.
    chat = client.chat.completions(
        model="sarvam-105b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful voice assistant. Reply in 1-2 short sentences, "
                    "in the same language the user spoke, as plain text suitable for "
                    "text-to-speech (no markdown, lists, or emoji)."
                ),
            },
            {"role": "user", "content": transcript},
        ],
    )
    reply = chat.choices[0].message.content.strip()
    print(f"Agent: {reply}")

    # 3. Speak: Bulbul turns the reply back into audio.
    language_code = getattr(stt, "language_code", None) or "hi-IN"
    audio = client.text_to_speech.convert(
        text=reply,
        language_code=language_code,
        model="bulbul:v4-flash",
        speaker="simran_en_customer",
    )
    out = input_path.with_name("agent_reply.wav")
    save(audio, str(out))
    print(f"Reply audio: {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
