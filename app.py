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

def smart_break_paragraphs(text, max_chars=350, user_break_keys=None):
    """
    Breaks text into paragraphs based on:
    1. Forced breaks before specific phrases (Default + User Custom).
    2. Length limits (max_chars) splitting at sentence boundaries.
    """
    if not text: return []
    
    # --- A. Define Forced Break Patterns ---
    # Default patterns that should always start a new line
    default_breaks = [
        r'Pair [IVX\d]+ is (?:in)?correct:?',      # Pair I is correct / Pair 2 is incorrect
        r'Statement [IVX\d]+ is (?:in)?correct:?', # Statement 1 is correct
        r'Option [a-d] is (?:in)?correct:?',       # Option a is correct
    ]
    
    # Add user custom keywords to the regex patterns
    if user_break_keys:
        for key in user_break_keys:
            if key.strip():
                # Escape to handle symbols safely
                default_breaks.append(re.escape(key.strip()))

    # Combine all into one regex: Look for these patterns
    # We use a special marker <SPLIT> to force splits before these phrases
    combined_pattern = "|".join(f"({p})" for p in default_breaks)
    
    # Insert <SPLIT> before the matches
    # logic: replace "Pattern" with "<SPLIT>Pattern"
    pre_processed_text = re.sub(rf'({combined_pattern})', r'<SPLIT>\1', text, flags=re.IGNORECASE)
    
    # Split by the marker
    raw_segments = pre_processed_text.split('<SPLIT>')
    
    # --- B. Process Each Segment for Length ---
    final_paragraphs = []
    
    for segment in raw_segments:
        segment = segment.strip()
        if not segment: continue
        
        # If segment is short, keep it as is
        if len(segment) < max_chars:
            final_paragraphs.append(segment)
        else:
            # If long, split by sentence logic
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
    Bolds specific keywords/phrases using Regex.
    """
    if not text: return ""
    
    # --- Default Patterns ---
    patterns = [
        r'(Option [a-d] is [a-z ]*correct:?)',
        r'(Statement \d+ is [a-z ]*correct:?)',
        r'(Pair [IVX\d]+ is [a-z ]*correct:?)',
        r'(Pair [IVX\d]+ is [a-z ]*incorrect:?)',
        r'(\b\d{4}\b)',  # Years like 1947
    ]
    
    # Add Common Acts/Articles
    keywords = ["Article \d+", "Section \d+", "Schedule \d+", "Amendment", "Act \d{4}"]
    patterns.extend(keywords)
    
    # --- User Custom Patterns ---
    if user_highlight_keys:
        for key in user_highlight_keys:
            if key.strip():
                patterns.append(re.escape(key.strip()))

    # Apply Bold Tags
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
            
            # Answer Cleaning
            raw_ans = ans_obj.get('solution') or ans_obj.get('answer') or 'N/A'
            clean_ans = str(raw_ans).replace('(', '').replace(')', '').strip().upper()
            
            # Explanation Extraction
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
    
    # --- Custom Styles ---
    style_q = ParagraphStyle('ElegantQuestion', parent=styles['Heading3'], fontSize=11, leading=15, textColor=colors.HexColor("#003366"), spaceAfter=8)
    style_meta = ParagraphStyle('MetaInfo', parent=styles['Normal'], fontSize=8, textColor=colors.grey, spaceAfter=2)
    style_opt = ParagraphStyle('Option', parent=styles['Normal'], fontSize=10, leading=14, leftIndent=20, spaceAfter=2)
    style_table_text = ParagraphStyle('TableText', parent=styles['Normal'], fontSize=10, leading=12)
    style_ans = ParagraphStyle('AnswerKey', parent=styles['Normal'], fontSize=10, textColor=colors.darkgreen, fontName='Helvetica-Bold', spaceBefore=8, spaceAfter=4)
    style_exp = ParagraphStyle('Explanation', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.black, alignment=0, spaceAfter=6)
    style_tips = ParagraphStyle('Tips', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor("#444444"), backColor=colors.HexColor("#FFF8DC"), borderPadding=4)

    story = []
    
    title = Paragraph(f"<b>{booklet_title}</b>", styles['Title'])
    subtitle = Paragraph(f"Generated on Streamlit • {len(data)} Questions", styles['Normal'])
    story.append(title)
    story.append(subtitle)
    story.append(Spacer(1, 30))
    
    match_pattern = re.compile(r"([A-Z])\.\s+(.*?)\s+-\s+(\d+)\.\s+(.*?)(?=\s[A-Z]\.| \Z|\Z)")

    for item in data:
        q_block = []
        
        # 1. Meta Data
        meta_text = f"<b>Q{item['id']}</b>"
        if item.get('source'): meta_text += f" &nbsp;|&nbsp; {item['source']}"
        q_block.append(Paragraph(meta_text, style_meta))
        
        # 2. Question Text
        q_text = item['question']
        matches = match_pattern.findall(q_text)
        
        if matches and ("Match" in q_text or "List" in q_text):
            match_start = re.search(match_pattern, q_text).start()
            intro_text = q_text[:match_start].strip()
            q_block.append(Paragraph(intro_text, style_q))
            q_block.append(Spacer(1, 6))
            
            table_data = [[Paragraph("<b>List I</b>", style_table_text), Paragraph("<b>List II</b>", style_table_text)]]
            for m in matches:
                col1 = Paragraph(f"<b>{m[0]}.</b> {m[1]}", style_table_text)
                col2 = Paragraph(f"<b>{m[2]}.</b> {m[3]}", style_table_text)
                table_data.append([col1, col2])
            
            t = Table(table_data, colWidths=[230, 230])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke), 
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), 
                ('VALIGN', (0,0), (-1,-1), 'TOP'), 
                ('PADDING', (0,0), (-1,-1), 6)
            ]))
            q_block.append(t)
            q_block.append(Spacer(1, 8))
        else:
            q_block.append(Paragraph(q_text, style_q))
        
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

        # A. Process Paragraphs (Apply forced breaks)
        exp_paragraphs = smart_break_paragraphs(main_exp, max_chars=350, user_break_keys=user_breaks)
        
        # B. Apply Highlighting to each paragraph
        if do_highlight:
            exp_paragraphs = [smart_highlight(p, user_highlights) for p in exp_paragraphs]
            if tips_text:
                tips_text = smart_highlight(tips_text, user_highlights)

        # C. Build Box
        exp_box_content = [[Paragraph("<b>Explanation:</b>", style_opt)]]
        for p_text in exp_paragraphs:
            exp_box_content.append([Paragraph(p_text, style_exp)])
        
        if tips_text:
            exp_box_content.append([Spacer(1, 6)])
            exp_box_content.append([Paragraph(f"<b>Important Tips:</b> {tips_text}", style_tips)])

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

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ PDF Settings")
    booklet_title = st.text_input("Booklet Title", value="Comprehensive Quiz Booklet")
    highlight_enabled = st.checkbox("Enable Smart Highlighting?", value=True)
    
    st.markdown("---")
    st.subheader("🛠️ Custom Formatting")
    
    # User Inputs for Custom Breaks/Highlights
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

    # Convert inputs to lists
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