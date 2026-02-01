import streamlit as st
import json
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

# ==========================================
# 1. HELPER: SMART TEXT PROCESSING
# ==========================================

def format_question_text(text):
    """
    Detects patterns inside questions and forces new lines:
    1. Numbered statements (e.g., "1. Statement...")
    2. Assertion / Reason keywords
    """
    if not text: return ""
    
    # 1. Numbered Statements (Space + Digit + Dot + Space + Capital Letter)
    pattern_num = r'(\s)(\d+\.\s+[A-Z])'
    text = re.sub(pattern_num, r'<br/>\2', text)
    
    # 2. Assertion / Reason Logic
    pattern_ar = r'(Assertion|Reason)'
    text = re.sub(pattern_ar, r'<br/><b>\1</b>', text)
    
    return text

def clean_table_row(right_text):
    """
    Detects if the 'Outro' question text (e.g. 'How many pairs...') 
    got merged into the last table cell.
    """
    split_markers = [
        "How many", "Select the", "Which of", "Consider the", 
        "In the context", "Select correct"
    ]
    
    for marker in split_markers:
        if marker in right_text:
            parts = right_text.split(marker, 1)
            return parts[0].strip(), marker + parts[1]
            
    if '\n' in right_text:
        parts = right_text.rsplit('\n', 1)
        if len(parts[1]) > 5 and parts[1][0].isupper():
             return parts[0].strip(), parts[1].strip()

    return right_text, ""

def smart_break_paragraphs(text, max_chars=350, user_break_keys=None):
    """
    Breaks text into paragraphs based on:
    1. Forced Breaks (Assertion, Reason, User Keys)
    2. Intelligent List Detection (Bullets, (a), (i), I. II.)
    3. Character Length
    """
    if not text: return []
    
    # --- A. Pre-Process: Intelligent List Detection ---
    # We replace list markers with <SPLIT>Marker to force breaks later.
    
    # 1. Strict Markers (Always split)
    # Bullets, Parenthesized (a)/(i), Lowercase Roman i. ii.
    # Excludes e.g., i.e. via negative lookbehind logic or strict formatting
    strict_patterns = [
        r'[•\-\*➢]\s+',                 # Bullets
        r'\((?:[a-zA-Z]|[ivxIVX]+|\d+)\)', # (a), (i), (1)
        r'\b[ivx]+\.\s+'                 # i. ii. iii. (Lowercase roman is safe)
    ]
    
    # 2. Conditional Uppercase Markers (I. II. A. B.)
    # SAFETY CHECK: Only split if preceded by Start of Line OR Punctuation (. ! ?)
    # This protects "Pulkesin II." (Preceded by 'n') vs "end. II." (Preceded by '.')
    conditional_pattern = r'(?:^|(?<=[.!?]\s))([IVX]+|[A-Z])\.\s+'

    # Apply Strict Patterns
    for p in strict_patterns:
        text = re.sub(f'({p})', r'<SPLIT>\1', text)
        
    # Apply Conditional Pattern (Manual handling to preserve the match)
    # We find "Dot Space Marker Dot Space" and insert SPLIT
    text = re.sub(conditional_pattern, r'<SPLIT>\1. ', text)

    # --- B. Forced Break Patterns (Keywords) ---
    default_breaks = [
        r'Pair [IVX\d]+ is (?:in)?correct:?',      
        r'Statement [IVX\d]+ is (?:in)?correct:?', 
        r'Option [a-d] is (?:in)?correct:?',
        r'Assertion', 
        r'Reason',
        r'\b[A-Z][a-zA-Z]+:' # Definition Headers (Pardon:, Note:)
    ]
    
    if user_break_keys:
        for key in user_break_keys:
            if key.strip():
                default_breaks.append(re.escape(key.strip()))

    combined_pattern = "|".join(f"({p})" for p in default_breaks)
    
    # Insert split marker <SPLIT> before the match
    text = re.sub(rf'({combined_pattern})', r'<SPLIT>\1', text, flags=re.IGNORECASE)
    
    # --- C. Process Segments ---
    raw_segments = text.split('<SPLIT>')
    final_paragraphs = []
    
    for segment in raw_segments:
        segment = segment.strip()
        if not segment: continue
        
        # If segment is huge, split by sentence length
        if len(segment) < max_chars:
            final_paragraphs.append(segment)
        else:
            current_chunk = ""
            sentences = re.split(r'(?<=[.!?])\s+', segment)
            for sentence in sentences:
                current_chunk += sentence + " "
                if len(current_chunk) > max_chars:
                    final_paragraphs.append(current_chunk.strip())
                    current_chunk = ""
            if current_chunk:
                final_paragraphs.append(current_chunk.strip())
                
    return final_paragraphs

def smart_highlight(text, user_highlight_keys=None):
    """
    Bolds/Colors specific keywords/phrases using Regex.
    """
    if not text: return ""
    
    # 1. Standard Bolding (Black Bold)
    patterns = [
        r'(Option [a-d] is [a-z ]*correct:?)',
        r'(Statement \d+ is [a-z ]*correct:?)',
        r'(Pair [IVX\d]+ is [a-z ]*correct:?)',
        r'(Pair [IVX\d]+ is [a-z ]*incorrect:?)',
        r'(\b\d{4}\b)', # Years
    ]
    keywords = ["Article \d+", "Section \d+", "Schedule \d+", "Amendment", "Act \d{4}"]
    patterns.extend(keywords)
    
    if user_highlight_keys:
        for key in user_highlight_keys:
            if key.strip():
                patterns.append(re.escape(key.strip()))

    for p in patterns:
        text = re.sub(rf'({p})', r'<b>\1</b>', text, flags=re.IGNORECASE)

    # 2. Definition Header Coloring (e.g. "Pardon:", "Note:")
    # Looks for Capitalized Word + Colon -> Bolds and Colors it Maroon
    def_pattern = r'(\b[A-Z][a-zA-Z]+:)'
    text = re.sub(def_pattern, r'<b><font color="#800000">\1</font></b>', text)

    return text

# ==========================================
# 2. MERGE ENGINE
# ==========================================
def merge_json_data(q_file, a_file):
    """
    Merges Question and Answer files.
    Robustly handles if q_file is a List OR a Dict (with 'questions' key).
    """
    try:
        # 1. Robust Question Loading
        q_raw = json.load(q_file)
        if isinstance(q_raw, dict) and 'questions' in q_raw:
            questions = q_raw['questions']
        elif isinstance(q_raw, list):
            questions = q_raw
        else:
            questions = []

        # 2. Answer Loading
        answers = json.load(a_file)
        ans_dict = {item['id']: item for item in answers}
        
        merged_data = []
        
        for q in questions:
            q_id = q.get('id')
            ans_obj = ans_dict.get(q_id, {})
            
            raw_ans = ans_obj.get('solution') or ans_obj.get('answer') or 'N/A'
            clean_ans = str(raw_ans).replace('(', '').replace(')', '').strip().upper()
            
            raw_exp = ans_obj.get('explanation', 'No explanation provided.')
            final_exp = ""
            if isinstance(raw_exp, dict):
                details = raw_exp.get('exp_details', '')
                tips = raw_exp.get('important_tips', '')
                final_exp = details
                if tips:
                    final_exp += f" ||TIPS|| {tips}" 
            else:
                final_exp = str(raw_exp)

            merged_data.append({
                'id': q_id,
                'question': q.get('question', ''),
                'options': q.get('options', {}),
                'source': q.get('source', ''),
                'answer_key': clean_ans,
                'explanation': final_exp
            })
            
        merged_data.sort(key=lambda x: x['id'])
        return merged_data
    except Exception as e:
        st.error(f"Error merging files: {e}")
        return []

# ==========================================
# 3. PDF ENGINE (OPTIMIZED)
# ==========================================
def create_elegant_pdf(data, booklet_title, do_highlight, user_breaks, user_highlights):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=36, leftMargin=36, 
        topMargin=36, bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    # --- Custom Colors ---
    COLOR_Q_TEXT = colors.HexColor("#2C3E50")   # Dark Slate Blue
    COLOR_META = colors.HexColor("#7F8C8D")     # Grey
    COLOR_ANS = colors.HexColor("#27AE60")      # Nephritis Green
    COLOR_TIPS_BG = colors.HexColor("#E8F8F5")  # Soft Mint
    COLOR_TABLE_HEAD = colors.HexColor("#D4E6F1") # Pale Blue
    
    # --- Styles ---
    style_q = ParagraphStyle('ElegantQuestion', parent=styles['Heading3'], fontSize=12, leading=15, textColor=COLOR_Q_TEXT, spaceAfter=6)
    style_meta = ParagraphStyle('MetaInfo', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#1A5276"), fontName='Helvetica-Bold', spaceAfter=2, spaceBefore=8)
    style_opt = ParagraphStyle('Option', parent=styles['Normal'], fontSize=11, leading=14, leftIndent=15, spaceAfter=1)
    style_table_text = ParagraphStyle('TableText', parent=styles['Normal'], fontSize=11, leading=13)
    style_ans = ParagraphStyle('AnswerKey', parent=styles['Normal'], fontSize=11, textColor=COLOR_ANS, fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=2)
    style_exp = ParagraphStyle('Explanation', parent=styles['Normal'], fontSize=11, leading=14, textColor=colors.black, alignment=0, spaceAfter=4)
    style_tips = ParagraphStyle('Tips', parent=styles['Normal'], fontSize=11, leading=14, textColor=colors.HexColor("#2C3E50"), backColor=COLOR_TIPS_BG, borderPadding=5)

    story = []
    
    title = Paragraph(f"<b>{booklet_title}</b>", styles['Title'])
    subtitle = Paragraph(f"Generated on Streamlit • {len(data)} Questions", styles['Normal'])
    story.append(title)
    story.append(subtitle)
    story.append(Spacer(1, 20))
    
    match_pattern = re.compile(r"(?:^|\s)([IVX]+|\d+|[A-Z])[\.\)]\s+(.*?)\s+-\s+(.*?)(?=\s(?:[IVX]+|\d+|[A-Z])[\.\)]|\Z)", re.DOTALL)

    for item in data:
        q_block = []
        
        # 1. Meta
        meta_text = f"Q{item['id']}"
        if item.get('source'): meta_text += f" | {item['source']}"
        q_block.append(Paragraph(meta_text, style_meta))
        
        # 2. Question Logic
        raw_q_text = item['question']
        table_matches = match_pattern.findall(raw_q_text)
        
        if table_matches and ("Match" in raw_q_text or "List" in raw_q_text or "pairs" in raw_q_text):
            match_start = re.search(match_pattern, raw_q_text).start()
            intro_text = raw_q_text[:match_start].strip()
            if intro_text:
                intro_text = format_question_text(intro_text)
                q_block.append(Paragraph(intro_text, style_q))
                q_block.append(Spacer(1, 4))
            
            table_data = [[Paragraph("<b>Item / List I</b>", style_table_text), Paragraph("<b>Match / List II</b>", style_table_text)]]
            outro_text_buffer = "" 
            
            for i, m in enumerate(table_matches):
                right_text_raw = m[2].strip()
                if i == len(table_matches) - 1:
                    clean_right, extracted_outro = clean_table_row(right_text_raw)
                    right_col = clean_right
                    outro_text_buffer = extracted_outro
                else:
                    right_col = right_text_raw
                
                left_col = f"<b>{m[0]}.</b> {m[1]}"
                table_data.append([Paragraph(left_col, style_table_text), Paragraph(right_col, style_table_text)])
            
            t = Table(table_data, colWidths=[250, 270])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), COLOR_TABLE_HEAD),
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('PADDING', (0,0), (-1,-1), 4)
            ]))
            q_block.append(t)
            
            if outro_text_buffer:
                q_block.append(Spacer(1, 6))
                q_block.append(Paragraph(f"<b>{outro_text_buffer}</b>", style_q))
            q_block.append(Spacer(1, 6))
        
        else:
            formatted_q_text = format_question_text(raw_q_text)
            q_block.append(Paragraph(formatted_q_text, style_q))
        
        # 3. Options
        options = item.get('options', {})
        if options:
            for key in sorted(options.keys()):
                opt_text = f"<b>({key})</b> {options[key]}"
                q_block.append(Paragraph(opt_text, style_opt))
        
        # 4. Answer
        ans_text = f"Correct Answer: {item['answer_key']}"
        q_block.append(Paragraph(ans_text, style_ans))
        
        # 5. Explanations
        raw_full_exp = item['explanation']
        main_exp = raw_full_exp.split("||TIPS||")[0]
        tips_text = raw_full_exp.split("||TIPS||")[1] if "||TIPS||" in raw_full_exp else ""

        exp_paragraphs = smart_break_paragraphs(main_exp, max_chars=350, user_break_keys=user_breaks)
        if do_highlight:
            exp_paragraphs = [smart_highlight(p, user_highlights) for p in exp_paragraphs]

        exp_box_content = [[Paragraph("<b>Explanation:</b>", style_opt)]]
        for p_text in exp_paragraphs:
            exp_box_content.append([Paragraph(p_text, style_exp)])
        
        if tips_text:
            exp_box_content.append([Spacer(1, 4)])
            tips_paragraphs = smart_break_paragraphs(tips_text, max_chars=350, user_break_keys=user_breaks)
            if do_highlight:
                tips_paragraphs = [smart_highlight(p, user_highlights) for p in tips_paragraphs]
            exp_box_content.append([Paragraph("<b>Important Tips:</b>", style_tips)])
            for t_text in tips_paragraphs:
                exp_box_content.append([Paragraph(t_text, style_tips)])

        t_exp = Table(exp_box_content, colWidths=[520])
        t_exp.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8F9FA")),
            ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('PADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        
        q_block.append(Spacer(1, 4))
        q_block.append(t_exp)
        q_block.append(Spacer(1, 10))
        q_block.append(Paragraph("_" * 90, style_meta))
        q_block.append(Spacer(1, 10))
        
        story.append(KeepTogether(q_block))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# 4. STREAMLIT UI
# ==========================================
st.set_page_config(page_title="Smart Quiz Publisher", page_icon="📘")
st.title("📘 Smart Quiz Publisher")

with st.sidebar:
    st.header("⚙️ PDF Settings")
    booklet_title = st.text_input("Booklet Title", value="Comprehensive Quiz Booklet")
    highlight_enabled = st.checkbox("Enable Smart Highlighting?", value=True)
    
    st.markdown("---")
    st.subheader("🛠️ Custom Formatting")
    break_input = st.text_input("Force Paragraph Break at:", placeholder="e.g. Note:, However, Conclusion:")
    highlight_input = st.text_input("Highlight Keywords:", placeholder="e.g. Supreme Court, Act 1935")

    user_breaks = [x.strip() for x in break_input.split(',')] if break_input else []
    user_highlights = [x.strip() for x in highlight_input.split(',')] if highlight_input else []

st.write("Upload your JSON files. I'll handle the formatting.")

col1, col2 = st.columns(2)
with col1: q_file = st.file_uploader("Upload Questions JSON", type="json")
with col2: a_file = st.file_uploader("Upload Answers JSON", type="json")

# --- SECTION INPUT (Global Attribute) ---
section_input = st.text_input("Enter Section Name (Attribute of final JSON)", placeholder="e.g. Ancient History")

# --- UI LOGIC WITH SESSION STATE ---
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
    st.session_state.pdf_bytes = None
    st.session_state.json_bytes = None

if q_file and a_file:
    if st.button("Generate Booklet"):
        # 1. Merge Data (Returns List of Questions)
        merged_data = merge_json_data(q_file, a_file)
        
        if merged_data:
            with st.spinner("Processing..."):
                # 2. Generate PDF (Passes List)
                pdf_bytes = create_elegant_pdf(merged_data, booklet_title, highlight_enabled, user_breaks, user_highlights)
                
                # 3. Generate JSON (Wraps List in Dictionary with 'section' key)
                final_json_structure = {
                    "section": section_input,
                    "questions": merged_data
                }
                json_bytes = json.dumps(final_json_structure, indent=2, ensure_ascii=False)
                
                # 4. Store in Session State
                st.session_state.processed_data = merged_data
                st.session_state.pdf_bytes = pdf_bytes
                st.session_state.json_bytes = json_bytes
                
                st.success(f"Success! Processed {len(merged_data)} questions.")

# --- DISPLAY DOWNLOAD BUTTONS (PERSISTENT) ---
if st.session_state.processed_data:
    # Generate Dynamic Filename
    safe_title = re.sub(r'[^\w\s-]', '', booklet_title).strip().replace(' ', '_')
    if not safe_title: safe_title = "quiz_data"
    
    pdf_filename = f"{safe_title}.pdf"
    json_filename = f"{safe_title}.json"

    st.markdown("### 📥 Download Your Files")
    b1, b2 = st.columns(2)
    with b1:
        st.download_button(
            label="📄 Download PDF", 
            data=st.session_state.pdf_bytes, 
            file_name=pdf_filename, 
            mime="application/pdf"
        )
    with b2:
        st.download_button(
            label="💾 Download Mapped JSON", 
            data=st.session_state.json_bytes, 
            file_name=json_filename, 
            mime="application/json"
        )