import streamlit as st
import google.generativeai as genai
import edge_tts
import asyncio
from supabase import create_client
import time
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Audiline (Free Edition)", layout="wide")
st.title("🎙️ Audiline: Gemini + EdgeTTS Edition")

# --- SIDEBAR: KEYS ---
with st.sidebar:
    st.header("⚙️ Configuration")
    GEMINI_KEY = st.text_input("Gemini API Key", type="password")
    SUPABASE_URL = st.text_input("Supabase URL")
    SUPABASE_KEY = st.text_input("Supabase Key", type="password")

    if not (GEMINI_KEY and SUPABASE_URL and SUPABASE_KEY):
        st.warning("⚠️ Enter all keys to start.")
        st.stop()

# --- INITIALIZE CLIENTS ---
# 1. Configure Gemini
genai.configure(api_key=GEMINI_KEY)
# model = genai.GenerativeModel('gemini-2.0-flash')

# Use the generic "latest" alias from your list
model = genai.GenerativeModel('models/gemini-flash-latest')

# 2. Configure Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- HELPER: FREE TEXT-TO-SPEECH ---
async def generate_audio_file(text, voice, filename):
    """Generates MP3 using free Microsoft Edge voices"""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

# --- UI: INPUT ---
col1, col2 = st.columns([2, 1])

with col1:
    raw_text = st.text_area("Paste News Article Here", height=300)

with col2:
    st.info("Settings")
    # Edge TTS Voices (High Quality & Free)
    voice_options = {
        "Guy (US)": "en-US-GuyNeural",
        "Jenny (US)": "en-US-JennyNeural",
        "Aria (US)": "en-US-AriaNeural",
        "Brian (UK)": "en-GB-RyanNeural",
        "Sonia (UK)": "en-GB-SoniaNeural"
    }
    selected_voice_name = st.selectbox("Voice", list(voice_options.keys()))
    voice_code = voice_options[selected_voice_name]
    
    bucket_tag = st.selectbox("Bucket", ["Technology", "Markets", "Politics", "Sports", "Global"])

# --- STEP 1: ANALYZE (GEMINI) ---
if st.button("1. Analyze (Gemini Free)"):
    if not raw_text:
        st.error("Paste text first!")
    else:
        with st.spinner("Asking Gemini..."):
            try:
                # UPDATED PROMPT: Much stricter instructions
                prompt = f"""
                You are a news editor system. You must output data in a specific format.
                
                Task:
                1. Write a punchy headline (max 8 words).
                2. Write a short audio script (max 60 words).
                
                Input Text: {raw_text}
                
                CRITICAL INSTRUCTION:
                Return ONLY the headline and script separated by a vertical pipe symbol (|).
                Do not use bolding, markdown, or labels like "Headline:".
                
                Format example: 
                Bitcoin hits 100k | Bitcoin has reached a new all time high today...
                """
                
                response = model.generate_content(prompt)
                result = response.text.strip() # Remove extra whitespace
                
                # UPDATED PARSING: More robust
                if "|" in result:
                    parts = result.split("|", 1)
                    # Clean up any accidental markdown stars (**) or whitespace
                    headline = parts[0].replace("*", "").strip()
                    script = parts[1].replace("*", "").strip()
                    
                    st.session_state['headline'] = headline
                    st.session_state['script'] = script
                    st.success("Analysis Complete!")
                else:
                    # Fallback if AI forgets the pipe: Try splitting by newline
                    if "\n" in result:
                        lines = [line for line in result.split("\n") if line.strip()]
                        if len(lines) >= 2:
                            st.session_state['headline'] = lines[0].replace("*", "").strip()
                            st.session_state['script'] = " ".join(lines[1:]).replace("*", "").strip()
                            st.success("Analysis Complete! (Fallback mode)")
                        else:
                            st.error(f"Format error. Raw output: {result}")
                    else:
                        st.error(f"Could not parse AI output. Raw result: {result}")
                        
            except Exception as e:
                st.error(f"Gemini Error: {e}")

# --- STEP 2: GENERATE & UPLOAD ---
if 'headline' in st.session_state:
    st.divider()
    st.subheader("📝 Review & Publish")
    
    final_headline = st.text_input("Headline", st.session_state['headline'])
    final_script = st.text_area("Script", st.session_state['script'])
    
    if st.button("2. Generate Audio & Publish"):
        with st.spinner("Generating Audio (Edge TTS)..."):
            try:
                # A. Generate Audio File Locally
                temp_filename = f"news_{int(time.time())}.mp3"
                asyncio.run(generate_audio_file(final_script, voice_code, temp_filename))
                
                # B. Upload to Supabase
                with open(temp_filename, 'rb') as f:
                    file_data = f.read()
                    
                supabase.storage.from_("news-audio").upload(
                    path=temp_filename,
                    file=file_data,
                    file_options={"content-type": "audio/mpeg"}
                )
                
                # C. Get Public URL
                public_url = f"{SUPABASE_URL}/storage/v1/object/public/news-audio/{temp_filename}"

                # D. Save to DB
                data = {
                    "headline": final_headline,
                    "summary": final_script,
                    "category": bucket_tag,
                    "audio_url": public_url
                }
                supabase.table("articles").insert(data).execute()
                
                st.success("✅ Published successfully!")
                st.audio(file_data) # Play it right here to confirm
                
                # Cleanup local file
                os.remove(temp_filename)
                
            except Exception as e:
                st.error(f"Error: {e}")