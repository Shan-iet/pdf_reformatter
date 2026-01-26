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
    Detects numbered statements in questions (e.g. '1. It was secular...')
    and forces them onto new lines for readability.
    """
    if not text: return ""
    
    # Pattern: Look for space + digit + dot + space + capital letter
    # We replace them with <br/> to force a line break in ReportLab
    pattern = r'(\s)(\d+\.\s+[A-Z])'
    formatted_text = re.sub(pattern, r'<br/>\2', text)
    return formatted_text

def smart_break_paragraphs(text, max_chars=350, user_break_keys=None):
    """
    Breaks text into paragraphs based on forced breaks and length limits.
    """
    if not text: return []
    
    # --- Forced Break Patterns ---
    default_breaks = [
        r'Pair [IVX\d]+ is (?:in)?correct:?',      
        r'Statement [IVX\d]+ is (?:in)?correct:?', 
        r'Option [a-d] is (?:in)?correct:?',       
    ]
    
    if user_break_keys:
        for key in user_break_keys:
            if key.strip():
                default_breaks.append(re.escape(key.strip()))

    combined_pattern = "|".join(f"({p})" for p in default_breaks)
    
    # Insert split marker
    pre_processed_text = re.sub(rf'({combined_pattern})', r'<SPLIT>\1', text, flags=re.IGNORECASE)
    raw_segments = pre_processed_text.split('<SPLIT>')
    
    # --- Process Segments ---
    final_paragraphs = []
    
    for segment in raw_segments:
        segment = segment.strip()
        if not segment: continue
        
        if len(segment) < max_chars:
            final_paragraphs.append(segment)
        else:
            current_chunk = ""
            # Split by sentence ending punctuation
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
    Bolds specific keywords/phrases using Regex.
    """
    if not text: return ""
    
    patterns = [
        r'(Option [a-d] is [a-z ]*correct:?)',
        r'(Statement \d+ is [a-z ]*correct:?)',
        r'(Pair [IVX\d]+ is [a-z ]*correct:?)',
        r'(Pair [IVX\d]+ is [a-z ]*incorrect:?)',
        r'(\b\d{4}\b)',  # Years
    ]
    
    keywords = ["Article \d+", "Section \d+", "Schedule \d+", "Amendment", "Act \d{4}"]
    patterns.extend(keywords)
    
    if user_highlight_keys:
        for key in user_highlight_keys:
            if key.strip():
                patterns.append(re.escape(key.strip()))

    for p in patterns:
        text = re.sub(rf'({p})', r'<b>\1</b>', text, flags=re.IGNORECASE)

    return text

# ==========================================
# 2. THE DATA MERGING ENGINE
# ==========================================
def merge_json_data(q_file, a_file):
    try:
        questions = json.load(q_file)
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
# 3. THE PDF DESIGN ENGINE
# ==========================================
def create_elegant_pdf(data, booklet_title, do_highlight, user_breaks, user_highlights):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=45, leftMargin=45, 
        topMargin=45, bottomMargin=45
    )
    
    styles = getSampleStyleSheet()
    
    # --- Custom Colors (Soothing Palette) ---
    COLOR_Q_TEXT = colors.HexColor("#2C3E50")   # Dark Slate Blue (Softer than black)
    COLOR_META = colors.HexColor("#7F8C8D")     # Grey for metadata
    COLOR_ANS = colors.HexColor("#27AE60")      # Nephritis Green
    COLOR_TIPS_BG = colors.HexColor("#E8F8F5")  # Very Pale Mint
    COLOR_TABLE_HEAD = colors.HexColor("#D4E6F1") # Pale Blue
    
    # --- Custom Styles ---
    style_q = ParagraphStyle(
        'ElegantQuestion', 
        parent=styles['Heading3'], 
        fontSize=12, 
        leading=16, 
        textColor=COLOR_Q_TEXT, 
        spaceAfter=8
    )
    
    style_meta = ParagraphStyle(
        'MetaInfo', 
        parent=styles['Normal'], 
        fontSize=11, 
        textColor=colors.HexColor("#1A5276"), # Dark Blue for ID
        fontName='Helvetica-Bold', 
        spaceAfter=4,
        spaceBefore=10
    )
    
    style_opt = ParagraphStyle(
        'Option', 
        parent=styles['Normal'], 
        fontSize=11, 
        leading=14, 
        leftIndent=20, 
        spaceAfter=2,
        textColor=colors.black
    )
    
    style_table_text = ParagraphStyle(
        'TableText', 
        parent=styles['Normal'], 
        fontSize=11, 
        leading=13,
        textColor=colors.black
    )
    
    style_ans = ParagraphStyle(
        'AnswerKey', 
        parent=styles['Normal'], 
        fontSize=11, 
        textColor=COLOR_ANS, 
        fontName='Helvetica-Bold', 
        spaceBefore=8, 
        spaceAfter=4
    )
    
    style_exp = ParagraphStyle(
        'Explanation', 
        parent=styles['Normal'], 
        fontSize=11, 
        leading=15, 
        textColor=colors.black, 
        alignment=0, 
        spaceAfter=6
    )
    
    style_tips = ParagraphStyle(
        'Tips', 
        parent=styles['Normal'], 
        fontSize=11, 
        leading=15, 
        textColor=colors.HexColor("#2C3E50"), 
        backColor=COLOR_TIPS_BG, 
        borderPadding=6
    )

    story = []
    
    # Title
    title = Paragraph(f"<b>{booklet_title}</b>", styles['Title'])
    subtitle = Paragraph(f"Generated on Streamlit • {len(data)} Questions", styles['Normal'])
    story.append(title)
    story.append(subtitle)
    story.append(Spacer(1, 30))
    
    # --- Regex for "Match Pairs" Table Detection ---
    # Captures: "I. Item - Match" OR "1. Item - Match" OR "A. Item - 1. Match"
    # Group 1: Identifier (I, II, 1, A) | Group 2: Left Side | Group 3: Right Side
    # Looks for ' - ' as the separator.
    match_pattern = re.compile(r"(?:^|\s)([IVX]+|\d+|[A-Z])[\.\)]\s+(.*?)\s+-\s+(.*?)(?=\s(?:[IVX]+|\d+|[A-Z])[\.\)]|\Z)", re.DOTALL)

    for item in data:
        q_block = []
        
        # 1. Meta Data
        meta_text = f"Q{item['id']}"
        if item.get('source'): meta_text += f" | {item['source']}"
        q_block.append(Paragraph(meta_text, style_meta))
        q_block.append(Spacer(1, 2))
        
        # 2. Question Text Analysis
        raw_q_text = item['question']
        
        # Check for Table Pattern (Match Lists / Pairs)
        table_matches = match_pattern.findall(raw_q_text)
        
        if table_matches and ("Match" in raw_q_text or "List" in raw_q_text or "pairs" in raw_q_text):
            # Extract Intro (Text before the first match)
            match_start = re.search(match_pattern, raw_q_text).start()
            intro_text = raw_q_text[:match_start].strip()
            intro_text = format_question_text(intro_text)
            
            q_block.append(Paragraph(intro_text, style_q))
            q_block.append(Spacer(1, 6))
            
            # Build Table
            table_data = [[Paragraph("<b>Item / List I</b>", style_table_text), Paragraph("<b>Match / List II</b>", style_table_text)]]
            
            for m in table_matches:
                # m[0]=ID (I), m[1]=Left (Asmaka), m[2]=Right (Godavari)
                # Clean up right side (sometimes it captures trailing newlines)
                right_text = m[2].strip()
                col1 = Paragraph(f"<b>{m[0]}.</b> {m[1]}", style_table_text)
                col2 = Paragraph(right_text, style_table_text)
                table_data.append([col1, col2])
            
            t = Table(table_data, colWidths=[230, 230])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), COLOR_TABLE_HEAD), # Pale Blue Header
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), 
                ('VALIGN', (0,0), (-1,-1), 'TOP'), 
                ('PADDING', (0,0), (-1,-1), 6)
            ]))
            q_block.append(t)
            
            # Check if there is text AFTER the table (e.g. "Select correct option")
            match_end = re.search(match_pattern, raw_q_text).end()
            # If the regex didn't catch the last item fully, we might lose tail text. 
            # Simple fix: usually the question ends with the pairs or options.
            # We assume Options handles the selection logic usually.
            
            q_block.append(Spacer(1, 8))
        else:
            # Standard Question
            formatted_q_text = format_question_text(raw_q_text)
            q_block.append(Paragraph(formatted_q_text, style_q))
        
        # 3. Options
        options = item.get('options', {})
        if options:
            for key in sorted(options.keys()):
                opt_text = f"<b>({key})</b> {options[key]}"
                q_block.append(Paragraph(opt_text, style_opt))
        
        # 4. Answer Key
        ans_text = f"Correct Answer: {item['answer_key']}"
        q_block.append(Paragraph(ans_text, style_ans))
        
        # 5. Explanation Logic
        raw_full_exp = item['explanation']
        main_exp = raw_full_exp.split("||TIPS||")[0]
        tips_text = raw_full_exp.split("||TIPS||")[1] if "||TIPS||" in raw_full_exp else ""

        # A. Process Main Explanation
        exp_paragraphs = smart_break_paragraphs(main_exp, max_chars=350, user_break_keys=user_breaks)
        if do_highlight:
            exp_paragraphs = [smart_highlight(p, user_highlights) for p in exp_paragraphs]

        # C. Build Explanation Box
        exp_box_content = [[Paragraph("<b>Explanation:</b>", style_opt)]]
        for p_text in exp_paragraphs:
            exp_box_content.append([Paragraph(p_text, style_exp)])
        
        # D. Process Tips
        if tips_text:
            exp_box_content.append([Spacer(1, 6)])
            
            # Smart Process Tips too
            tips_paragraphs = smart_break_paragraphs(tips_text, max_chars=350, user_break_keys=user_breaks)
            if do_highlight:
                tips_paragraphs = [smart_highlight(p, user_highlights) for p in tips_paragraphs]
            
            exp_box_content.append([Paragraph("<b>Important Tips:</b>", style_tips)])
            for t_text in tips_paragraphs:
                exp_box_content.append([Paragraph(t_text, style_tips)])

        t_exp = Table(exp_box_content, colWidths=[460])
        t_exp.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8F9FA")),
            ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('PADDING', (0,0), (-1,-1), 8),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        
        q_block.append(Spacer(1, 4))
        q_block.append(t_exp)
        q_block.append(Spacer(1, 15))
        q_block.append(Paragraph("_" * 80, style_meta))
        q_block.append(Spacer(1, 15))
        
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
    
    break_input = st.text_input(
        "Force New Paragraph at (comma separated):",
        placeholder="e.g. Note:, However, Conclusion:",
        help="The explanation will break into a new line BEFORE these words."
    )
    
    highlight_input = st.text_input(
        "Highlight Keywords (comma separated):",
        placeholder="e.g. Supreme Court, Act 1935",
        help="These words will be bolded automatically."
    )

    user_breaks = [x.strip() for x in break_input.split(',')] if break_input else []
    user_highlights = [x.strip() for x in highlight_input.split(',')] if highlight_input else []

st.write("Upload your JSON files. I'll handle the formatting.")

col1, col2 = st.columns(2)
with col1: q_file = st.file_uploader("Upload Questions JSON", type="json")
with col2: a_file = st.file_uploader("Upload Answers JSON", type="json")

if q_file and a_file:
    if st.button("Generate Booklet"):
        merged_data = merge_json_data(q_file, a_file)
        if merged_data:
            with st.spinner("Designing PDF..."):
                pdf_bytes = create_elegant_pdf(
                    merged_data, 
                    booklet_title, 
                    highlight_enabled,
                    user_breaks,
                    user_highlights
                )
                
                st.success(f"Success! Processed {len(merged_data)} questions.")
                st.download_button(
                    label="📥 Download PDF", 
                    data=pdf_bytes, 
                    file_name="Quiz_Booklet.pdf", 
                    mime="application/pdf"
                )