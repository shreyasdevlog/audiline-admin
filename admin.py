import streamlit as st
import google.generativeai as genai
import requests  # Using Direct REST API for Deepgram
from supabase import create_client
import time
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Audiline Admin", layout="wide")
st.title("🎙️ Audiline Newsroom (Unified Schema)")

# --- SIDEBAR: CONFIGURATION ---
with st.sidebar:
    st.header("⚙️ Settings")
    
    # 1. API Keys
    GEMINI_KEY = st.text_input("Gemini API Key", type="password")
    SUPABASE_URL = st.text_input("Supabase URL")
    SUPABASE_KEY = st.text_input("Supabase Service Key", type="password", help="Use the SERVICE_ROLE key")
    DEEPGRAM_KEY = st.text_input("Deepgram API Key", type="password")

    if not (GEMINI_KEY and SUPABASE_URL and SUPABASE_KEY and DEEPGRAM_KEY):
        st.warning("⚠️ Enter all keys to proceed.")
        st.stop()

# --- INITIALIZE CLIENTS ---
try:
    # 1. Configure Gemini
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('models/gemini-flash-latest')

    # 2. Configure Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 3. Deepgram: No initialization needed (We use REST API)

except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# --- HELPER: AUDIO GENERATION (DIRECT REST API) ---
def generate_audio_file(text, filename):
    """Generates MP3 using Deepgram REST API (Robust)"""
    try:
        url = "https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mp3"
        headers = {
            "Authorization": f"Token {DEEPGRAM_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"text": text}

        # Make the request
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            # Save the binary content to file
            with open(filename, "wb") as f:
                f.write(response.content)
            return True
        else:
            st.error(f"Deepgram API Error: {response.text}")
            return False
        
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return False

# --- UI: INPUT SECTION ---
col1, col2 = st.columns([2, 1])

with col1:
    raw_text = st.text_area("Paste News Article Text Here", height=300)

with col2:
    st.info("Metadata")
    
    # 1. THE NEW STANDARDIZED BUCKETS
    bucket_tag = st.selectbox("Category", [
        "Money & Markets", 
        "Technology", 
        "Sports", 
        "World", 
        "India", 
        "Entertainment"
    ])
    
    # 2. THE PULSE FLAGS (Checkboxes)
    st.markdown("### Pulse Flags")
    is_breaking = st.checkbox("🔥 Breaking News")
    is_crisis = st.checkbox("🚨 Crisis Alert")

# --- STEP 1: ANALYZE (GEMINI) ---
if st.button("1. Analyze Article"):
    if not raw_text:
        st.error("Please paste some text first.")
    else:
        with st.spinner("Consulting Gemini..."):
            try:
                prompt = f"""
                You are a news editor system. 
                Task:
                1. Write a punchy headline (max 8 words).
                2. Write a short audio script (max 60 words).
                
                Input Text: {raw_text}
                
                CRITICAL INSTRUCTION:
                Return ONLY the headline and script separated by a vertical pipe symbol (|).
                Do not use bolding, markdown, or labels.
                
                Format example: 
                Bitcoin hits 100k | Bitcoin has reached a new all time high today...
                """
                
                response = model.generate_content(prompt)
                result = response.text.strip()
                
                # PARSING LOGIC
                if "|" in result:
                    parts = result.split("|", 1)
                    st.session_state['headline'] = parts[0].replace("*", "").strip()
                    st.session_state['script'] = parts[1].replace("*", "").strip()
                    st.success("Analysis Complete!")
                else:
                    lines = [line for line in result.split("\n") if line.strip()]
                    if len(lines) >= 2:
                        st.session_state['headline'] = lines[0].replace("*", "").strip()
                        st.session_state['script'] = " ".join(lines[1:]).replace("*", "").strip()
                        st.success("Analysis Complete! (Fallback used)")
                    else:
                        st.error(f"Could not parse output. Raw: {result}")

            except Exception as e:
                st.error(f"Gemini API Error: {e}")

# --- STEP 2: PUBLISH (REST API + SUPABASE) ---
if 'headline' in st.session_state:
    st.divider()
    st.subheader("📝 Review & Publish")
    
    final_headline = st.text_input("Headline", st.session_state['headline'])
    final_script = st.text_area("Script", st.session_state['script'])
    
    if st.button("2. Generate Audio & Publish"):
        with st.spinner("Generating Human-like Audio..."):
            
            temp_filename = f"news_{int(time.time())}.mp3"
            success = generate_audio_file(final_script, temp_filename)
            
            if success:
                try:
                    # B. Upload to Supabase Storage
                    with open(temp_filename, 'rb') as f:
                        file_data = f.read()
                        
                    supabase.storage.from_("news-audio").upload(
                        path=temp_filename,
                        file=file_data,
                        file_options={"content-type": "audio/mpeg"}
                    )
                    
                    # C. Construct Public URL
                    public_url = f"{SUPABASE_URL}/storage/v1/object/public/news-audio/{temp_filename}"

                    # D. Calculate Duration
                    word_count = len(final_script.split())
                    estimated_duration = int(word_count / 2.5)

                    # E. Save Metadata (NOW WITH PULSE FLAGS)
                    data = {
                        "headline": final_headline,
                        "summary": final_script,
                        "category": bucket_tag,
                        "audio_url": public_url,
                        "duration_seconds": estimated_duration,
                        "is_breaking": is_breaking, # <--- New Flag
                        "is_crisis": is_crisis      # <--- New Flag
                    }
                    supabase.table("articles").insert(data).execute()
                    
                    st.success(f"✅ Published to {bucket_tag}!")
                    if is_breaking:
                        st.warning("Tagged as Breaking News")
                    st.write(f"**Duration:** {estimated_duration} seconds")
                    st.audio(file_data) 
                    
                except Exception as e:
                    st.error(f"Upload Error: {e}")
                finally:
                    if os.path.exists(temp_filename):
                        os.remove(temp_filename)