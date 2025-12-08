import streamlit as st
import google.generativeai as genai
from gtts import gTTS
from supabase import create_client
import time
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Audiline Admin", layout="wide")
st.title("🎙️ Audiline Newsroom (Google Edition)")

# --- SIDEBAR: CONFIGURATION ---
with st.sidebar:
    st.header("⚙️ Settings")
    
    # 1. API Keys (Works locally and in Cloud)
    # We use text_input so you can paste them easily. 
    # (Later you can switch to st.secrets for auto-filling)
    GEMINI_KEY = st.text_input("Gemini API Key", type="password")
    SUPABASE_URL = st.text_input("Supabase Project URL")
    SUPABASE_KEY = st.text_input("Supabase Service Role Key", type="password", help="Use the SERVICE_ROLE key to bypass RLS errors")

    if not (GEMINI_KEY and SUPABASE_URL and SUPABASE_KEY):
        st.warning("⚠️ Enter all keys to proceed.")
        st.stop()

# --- INITIALIZE CLIENTS ---
try:
    # 1. Configure Gemini
    genai.configure(api_key=GEMINI_KEY)
    # Using 'flash-latest' to avoid the "Free Tier 0 limit" on 2.0 models
    model = genai.GenerativeModel('models/gemini-flash-latest')

    # 2. Configure Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# --- HELPER: AUDIO GENERATION (gTTS) ---
def generate_audio_file(text, filename):
    """Generates MP3 using Google TTS (Free & Reliable)"""
    try:
        # lang='en', tld='com' (Standard US English)
        # You can change tld to 'co.uk' for British, 'co.in' for Indian accent
        tts = gTTS(text=text, lang='en', tld='co.uk') 
        tts.save(filename)
        return True
    except Exception as e:
        st.error(f"Audio Generation Failed: {e}")
        return False

# --- UI: INPUT SECTION ---
col1, col2 = st.columns([2, 1])

with col1:
    raw_text = st.text_area("Paste News Article Text Here", height=300)

with col2:
    st.info("Metadata")
    bucket_tag = st.selectbox("Bucket", ["Technology", "Markets", "Politics", "Sports", "Global"])

# --- STEP 1: ANALYZE (GEMINI) ---
if st.button("1. Analyze Article"):
    if not raw_text:
        st.error("Please paste some text first.")
    else:
        with st.spinner("Consulting Gemini..."):
            try:
                # STRICT PROMPT to ensure we get the pipe (|) format
                prompt = f"""
                You are a news editor system. 
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
                result = response.text.strip()
                
                # PARSING LOGIC
                if "|" in result:
                    parts = result.split("|", 1)
                    headline = parts[0].replace("*", "").strip()
                    script = parts[1].replace("*", "").strip()
                    
                    st.session_state['headline'] = headline
                    st.session_state['script'] = script
                    st.success("Analysis Complete!")
                else:
                    # Fallback logic if AI forgets the pipe
                    st.warning("AI format was inconsistent, trying to parse...")
                    lines = [line for line in result.split("\n") if line.strip()]
                    if len(lines) >= 2:
                        st.session_state['headline'] = lines[0].replace("*", "").strip()
                        st.session_state['script'] = " ".join(lines[1:]).replace("*", "").strip()
                        st.success("Analysis Complete! (Fallback used)")
                    else:
                        st.error(f"Could not parse output. Raw: {result}")

            except Exception as e:
                st.error(f"Gemini API Error: {e}")

# --- STEP 2: PUBLISH (gTTS + SUPABASE) ---
if 'headline' in st.session_state:
    st.divider()
    st.subheader("📝 Review & Publish")
    
    # Editable fields so you can fix AI mistakes
    final_headline = st.text_input("Headline", st.session_state['headline'])
    final_script = st.text_area("Script", st.session_state['script'])
    
    if st.button("2. Generate Audio & Publish"):
        with st.spinner("Generating Audio & Uploading..."):
            
            # A. Generate Audio File Locally
            temp_filename = f"news_{int(time.time())}.mp3"
            success = generate_audio_file(final_script, temp_filename)
            
            if success:
                try:
                    # B. Upload to Supabase Storage
                    with open(temp_filename, 'rb') as f:
                        file_data = f.read()
                        
                    storage_response = supabase.storage.from_("news-audio").upload(
                        path=temp_filename,
                        file=file_data,
                        file_options={"content-type": "audio/mpeg"}
                    )
                    
                    # C. Construct Public URL
                    # NOTE: Ensure your 'news-audio' bucket is set to PUBLIC in Supabase
                    public_url = f"{SUPABASE_URL}/storage/v1/object/public/news-audio/{temp_filename}"

                    # D. Save Metadata to Database
                    data = {
                        "headline": final_headline,
                        "summary": final_script,
                        "category": bucket_tag,
                        "audio_url": public_url
                    }
                    supabase.table("articles").insert(data).execute()
                    
                    # Success Message
                    st.success("✅ Published successfully!")
                    st.write(f"**Headline:** {final_headline}")
                    st.audio(file_data) # Play audio locally to confirm
                    
                except Exception as e:
                    st.error(f"Upload Error: {e}")
                finally:
                    # Cleanup: Remove the temporary file from your computer/server
                    if os.path.exists(temp_filename):
                        os.remove(temp_filename)
