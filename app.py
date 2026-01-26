import streamlit as st
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO

# --- 1. THE MERGE ENGINE ---
def merge_json_data(q_file, a_file):
    """
    Reads two JSON files and merges them into a single list based on 'id'.
    """
    try:
        # Load JSONs
        questions = json.load(q_file)
        answers = json.load(a_file)
        
        # Convert answers to a dictionary for fast lookup: {1: {...}, 2: {...}}
        ans_dict = {item['id']: item for item in answers}
        
        merged_data = []
        
        for q in questions:
            q_id = q.get('id')
            
            # Find matching answer
            matching_ans = ans_dict.get(q_id, {})
            
            # Create unified object
            merged_item = {
                'id': q_id,
                'question': q.get('question', ''),
                'options': q.get('options', {}),
                'source': q.get('source', ''),
                'answer_key': matching_ans.get('answer', 'N/A'),
                'explanation': matching_ans.get('explanation', 'No explanation provided.')
            }
            merged_data.append(merged_item)
            
        return merged_data
        
    except Exception as e:
        st.error(f"Error merging files: {e}")
        return []

# --- 2. THE ELEGANT PDF DESIGNER ---
def create_elegant_pdf(data):
    """
    Generates a professionally styled PDF using ReportLab.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=40, leftMargin=40, 
        topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # --- CUSTOM STYLES ---
    # 1. Question Style (Dark Blue, Bold)
    style_q = ParagraphStyle(
        'ElegantQuestion',
        parent=styles['Heading3'],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#003366"), # Navy Blue
        spaceAfter=6
    )
    
    # 2. Source/Tag Style (Small, Grey)
    style_meta = ParagraphStyle(
        'MetaInfo',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        spaceAfter=4
    )
    
    # 3. Option Style (Indented)
    style_opt = ParagraphStyle(
        'Option',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        leftIndent=20,
        spaceAfter=2
    )
    
    # 4. Answer Key Style (Bold Green)
    style_ans = ParagraphStyle(
        'AnswerKey',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.darkgreen,
        fontName='Helvetica-Bold',
        spaceBefore=6,
        spaceAfter=2
    )
    
    # 5. Explanation Style (Justified, inside a box logic)
    style_exp = ParagraphStyle(
        'Explanation',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.black,
    )

    story = []
    
    # Add Title
    title = Paragraph("<b>Comprehensive Quiz Booklet</b>", styles['Title'])
    story.append(title)
    story.append(Spacer(1, 20))
    
    for item in data:
        # Create a list of flowables for THIS specific question
        # We use KeepTogether so a question doesn't split awkwardly across pages
        q_block = []
        
        # A. ID and Source
        meta_text = f"<b>Q{item['id']}</b>"
        if item.get('source'):
            meta_text += f"  |  Source: {item['source']}"
        q_block.append(Paragraph(meta_text, style_meta))
        
        # B. Question Text
        q_block.append(Paragraph(item['question'], style_q))
        
        # C. Options
        options = item.get('options', {})
        if options:
            # Sort options if keys are a,b,c,d
            for key in sorted(options.keys()):
                opt_text = f"<b>({key})</b> {options[key]}"
                q_block.append(Paragraph(opt_text, style_opt))
        
        # D. Answer Key
        ans_text = f"Correct Answer: {item['answer_key'].upper()}"
        q_block.append(Paragraph(ans_text, style_ans))
        
        # E. Explanation Box (Using a Table for the background effect)
        if item['explanation']:
            exp_content = [
                [Paragraph("<b>Explanation:</b>", style_opt)],
                [Paragraph(item['explanation'], style_exp)]
            ]
            
            # Create a table with light grey background
            t = Table(exp_content, colWidths=[450])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F2F2F2")), # Light Grey
                ('BOX', (0,0), (-1,-1), 0.25, colors.grey), # Thin border
                ('PADDING', (0,0), (-1,-1), 8), # Padding inside box
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ]))
            q_block.append(Spacer(1, 4))
            q_block.append(t)
        
        q_block.append(Spacer(1, 15))
        q_block.append(Paragraph("_" * 70, style_meta)) # Divider line
        q_block.append(Spacer(1, 15))
        
        # Add the whole block to the story
        story.append(KeepTogether(q_block))

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 3. STREAMLIT UI ---
st.set_page_config(page_title="JSON to Quiz PDF", page_icon="📘")
st.title("📘 JSON Quiz Publisher")
st.markdown("""
Upload your **Questions JSON** and **Answers JSON**. 
I will merge them into a clean, readable PDF booklet.
""")

col1, col2 = st.columns(2)

with col1:
    q_file = st.file_uploader("Upload Questions (JSON)", type="json")

with col2:
    a_file = st.file_uploader("Upload Answers (JSON)", type="json")

if q_file and a_file:
    if st.button("Generate Booklet"):
        with st.spinner("Designing PDF..."):
            # 1. Merge
            merged_data = merge_json_data(q_file, a_file)
            
            if merged_data:
                st.success(f"Successfully merged {len(merged_data)} questions!")
                
                # 2. Generate PDF
                pdf_data = create_elegant_pdf(merged_data)
                
                # 3. Download
                st.download_button(
                    label="📥 Download Quiz Booklet (PDF)",
                    data=pdf_data,
                    file_name="Quiz_Booklet.pdf",
                    mime="application/pdf"
                )
            else:
                st.error("Could not merge data. Please check JSON format.")