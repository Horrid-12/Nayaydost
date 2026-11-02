import streamlit as st
import requests
import base64

SARVAM_API_KEY = "YOUR_SARVAM_API_KEY_HERE"  # Replace with your actual key

st.set_page_config(page_title="Sarvam AI Multilingual Voice Hub", layout="centered")

st.title("🎙️ Sarvam AI Multilingual Voice Assistant")
st.write("Bridging language barriers using Speech, Translation, and Voice synthesis.")

# Sidebar Settings
st.sidebar.header("Configuration")
target_lang = st.sidebar.selectbox(
    "Target Language",
    options=[
        ("hi-IN", "Hindi"),
        ("mr-IN", "Marathi"),
        ("bn-IN", "Bengali"),
        ("ta-IN", "Tamil"),
        ("te-IN", "Telugu"),
        ("gu-IN", "Gujarati"),
    ],
    format_func=lambda x: x[1]
)[0]

# Mode Selection
app_mode = st.radio("Choose Input Mode:", ["Text Translation & Voice", "Speech-to-Text Transcription"])

if app_mode == "Text Translation & Voice":
    input_text = st.text_area("Enter message in English (e.g., Medical advice, farming advisory):", 
                              value="Take this tablet twice a day after meals. Drink plenty of warm water.")
    
    if st.button("Translate & Speak"):
        if not input_text.strip():
            st.warning("Please enter some text.")
        else:
            with st.spinner("Translating via Sarvam Mayura..."):
                headers = {
                    "api-subscription-key": SARVAM_API_KEY,
                    "Content-Type": "application/json"
                }
                
                # 1. Call Translation API
                trans_payload = {
                    "input": input_text,
                    "source_language_code": "en-IN",
                    "target_language_code": target_lang,
                    "mode": "formal",
                    "model": "mayura:v1"
                }
                
                trans_res = requests.post("https://api.sarvam.ai/translate", json=trans_payload, headers=headers)
                
                if trans_res.status_code == 200:
                    translated_text = trans_res.json().get("translated_text", "")
                    st.success("Translated Output:")
                    st.markdown(f"### {translated_text}")
                    
                    # 2. Call Text-to-Speech API
                    with st.spinner("Generating speech via Sarvam Bulbul..."):
                        tts_payload = {
                            "inputs": [translated_text],
                            "target_language_code": target_lang,
                            "speaker": "meera",
                            "pace": 1.0,
                            "model": "bulbul:v1"
                        }
                        tts_res = requests.post("https://api.sarvam.ai/text-to-speech", json=tts_payload, headers=headers)
                        
                        if tts_res.status_code == 200:
                            audios = tts_res.json().get("audios", [])
                            if audios:
                                audio_base64 = audios[0]
                                audio_bytes = base64.b64decode(audio_base64)
                                st.audio(audio_bytes, format="audio/wav")
                        else:
                            st.error(f"TTS API Error: {tts_res.text}")
                else:
                    st.error(f"Translation API Error: {trans_res.text}")

elif app_mode == "Speech-to-Text Transcription":
    uploaded_file = st.file_uploader("Upload an audio file (WAV/MP3):", type=["wav", "mp3"])
    
    if uploaded_file and st.button("Transcribe Audio"):
        with st.spinner("Transcribing via Sarvam Saaras..."):
            headers = {"api-subscription-key": SARVAM_API_KEY}
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            data = {
                "model": "saaras:v4",
                "language_code": "unknown"  # Auto-detect language
            }
            
            stt_res = requests.post("https://api.sarvam.ai/speech-to-text", files=files, data=data, headers=headers)
            
            if stt_res.status_code == 200:
                transcript = stt_res.json().get("transcript", "")
                st.success("Transcription Result:")
                st.write(transcript)
            else:
                st.error(f"STT API Error: {stt_res.text}")