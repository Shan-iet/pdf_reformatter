import streamlit as st
import json
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

# ==========================================
# 1. THE DATA MERGING ENGINE (UPDATED)
# ==========================================
def merge_json_data(q_file, a_file):
    """
    Combines Question JSON and Answer JSON.
    Handles variable keys ('solution' vs 'answer') and nested explanation objects.
    """
    try:
        # Load the uploaded files
        questions = json.load(q_file)
        answers = json.load(a_file)
        
        # Create a dictionary for answers for instant lookup
        ans_dict = {item['id']: item for item in answers}
        
        merged_data = []
        
        for q in questions:
            q_id = q.get('id')
            ans_obj = ans_dict.get(q_id, {})
            
            # --- 1. SMART ANSWER EXTRACTION ---
            # Check for 'solution' (new format) or 'answer' (old format)
            raw_ans = ans_obj.get('solution') or ans_obj.get('answer') or 'N/A'
            # Clean it: "(b)" -> "B", "b" -> "B"
            clean_ans = str(raw_ans).replace('(', '').replace(')', '').strip().upper()
            
            # --- 2. SMART EXPLANATION EXTRACTION ---
            raw_exp = ans_obj.get('explanation', 'No explanation provided.')
            final_exp = ""
            
            if isinstance(raw_exp, dict):
                # It's a complex object with details and tips
                details = raw_exp.get('exp_details', '')
                tips = raw_exp.get('important_tips', '')
                
                final_exp = details
                if tips:
                    # Add tips with a bold header
                    final_exp += f"<br/><br/><b>Important Tips:</b> {tips}"
            else:
                # It's just a simple string
                final_exp = str(raw_exp)

            # Build the unified object
            merged_item = {
                'id': q_id,
                'question': q.get('question', ''),
                'options': q.get('options', {}),
                'source': q.get('source', ''),
                'answer_key': clean_ans,
                'explanation': final_exp
            }
            merged_data.append(merged_item)
            
        merged_data.sort(key=lambda x: x['id'])
        return merged_data
        
    except Exception as e:
        st.error(f"Error merging JSON files: {e}")
        return []

# ==========================================
# 2. THE PDF DESIGN ENGINE
# ==========================================
def create_elegant_pdf(data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=45, leftMargin=45, 
        topMargin=45, bottomMargin=45
    )
    
    styles = getSampleStyleSheet()
    
    # --- Styles ---
    style_q = ParagraphStyle('ElegantQuestion', parent=styles['Heading3'], fontSize=11, leading=15, textColor=colors.HexColor("#003366"), spaceAfter=8)
    style_meta = ParagraphStyle('MetaInfo', parent=styles['Normal'], fontSize=8, textColor=colors.grey, spaceAfter=2)
    style_opt = ParagraphStyle('Option', parent=styles['Normal'], fontSize=10, leading=14, leftIndent=20, spaceAfter=2)
    style_table_text = ParagraphStyle('TableText', parent=styles['Normal'], fontSize=10, leading=12)
    style_ans = ParagraphStyle('AnswerKey', parent=styles['Normal'], fontSize=10, textColor=colors.darkgreen, fontName='Helvetica-Bold', spaceBefore=8, spaceAfter=4)
    style_exp = ParagraphStyle('Explanation', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.black, alignment=0)

    story = []
    
    # Title Page
    title = Paragraph("<b>Comprehensive Quiz Booklet</b>", styles['Title'])
    subtitle = Paragraph(f"Generated on Streamlit • {len(data)} Questions", styles['Normal'])
    story.append(title)
    story.append(subtitle)
    story.append(Spacer(1, 30))
    
    # Regex for "Match List" (A. Item - 1. Desc)
    match_pattern = re.compile(r"([A-Z])\.\s+(.*?)\s+-\s+(\d+)\.\s+(.*?)(?=\s[A-Z]\.| \Z|\Z)")

    for item in data:
        q_block = []
        
        # 1. Meta Data
        meta_text = f"<b>Q{item['id']}</b>"
        if item.get('source'):
            meta_text += f" &nbsp;|&nbsp; {item['source']}"
        q_block.append(Paragraph(meta_text, style_meta))
        
        # 2. Question Text & Smart Table Detection
        q_text = item['question']
        matches = match_pattern.findall(q_text)
        
        # Trigger Table Mode only if we see the pattern AND keywords like "Match" or "List"
        if matches and ("Match" in q_text or "List" in q_text):
            # Extract Intro
            match_start = re.search(match_pattern, q_text).start()
            intro_text = q_text[:match_start].strip()
            q_block.append(Paragraph(intro_text, style_q))
            q_block.append(Spacer(1, 6))
            
            # Build Table
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
                ('PADDING', (0,0), (-1,-1), 6),
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
        
        # 5. Explanation Box
        if item['explanation']:
            exp_content = [
                [Paragraph("<b>Explanation:</b>", style_opt)],
                [Paragraph(item['explanation'], style_exp)]
            ]
            t_exp = Table(exp_content, colWidths=[460])
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
# 3. UI
# ==========================================
st.set_page_config(page_title="Smart Quiz Publisher", page_icon="📘")
st.title("📘 Smart Quiz Publisher")
st.write("Upload your JSON files. I'll handle the rest.")

col1, col2 = st.columns(2)
with col1: q_file = st.file_uploader("Upload Questions JSON", type="json")
with col2: a_file = st.file_uploader("Upload Answers JSON", type="json")

if q_file and a_file:
    if st.button("Generate Booklet"):
        merged_data = merge_json_data(q_file, a_file)
        if merged_data:
            pdf_bytes = create_elegant_pdf(merged_data)
            st.success(f"Success! Processed {len(merged_data)} questions.")
            st.download_button("📥 Download PDF", pdf_bytes, "Quiz_Booklet.pdf", "application/pdf")