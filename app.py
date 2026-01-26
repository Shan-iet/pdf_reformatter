import streamlit as st
import json
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

# ==========================================
# 1. THE DATA MERGING ENGINE
# ==========================================
def merge_json_data(q_file, a_file):
    """
    Combines Question JSON and Answer JSON into a single list of objects.
    """
    try:
        # Load the uploaded files
        questions = json.load(q_file)
        answers = json.load(a_file)
        
        # Create a dictionary for answers for instant O(1) lookup
        # Format: {1: {...data...}, 2: {...data...}}
        ans_dict = {item['id']: item for item in answers}
        
        merged_data = []
        
        for q in questions:
            q_id = q.get('id')
            
            # Fetch corresponding answer object
            matching_ans = ans_dict.get(q_id, {})
            
            # Build the unified object
            merged_item = {
                'id': q_id,
                'question': q.get('question', ''),
                'options': q.get('options', {}),
                'source': q.get('source', ''),
                'answer_key': matching_ans.get('answer', 'N/A'),
                'explanation': matching_ans.get('explanation', 'No explanation available.')
            }
            merged_data.append(merged_item)
            
        # Sort by ID just in case
        merged_data.sort(key=lambda x: x['id'])
        return merged_data
        
    except Exception as e:
        st.error(f"Error merging JSON files: {e}")
        return []

# ==========================================
# 2. THE PDF DESIGN ENGINE
# ==========================================
def create_elegant_pdf(data):
    """
    Generates a PDF with smart detection for 'Match List' questions.
    """
    buffer = BytesIO()
    
    # Page Settings: A4 with comfortable margins
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=45, leftMargin=45, 
        topMargin=45, bottomMargin=45
    )
    
    styles = getSampleStyleSheet()
    
    # --- Custom Styling Definitions ---
    
    # Question: Navy Blue, Bold, Slightly Larger
    style_q = ParagraphStyle(
        'ElegantQuestion',
        parent=styles['Heading3'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#003366"), 
        spaceAfter=8
    )
    
    # Meta Info: Small Grey Text (ID | Source)
    style_meta = ParagraphStyle(
        'MetaInfo',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        spaceAfter=2
    )
    
    # Options: Indented
    style_opt = ParagraphStyle(
        'Option',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        leftIndent=20,
        spaceAfter=2
    )
    
    # Table Content (for Match List)
    style_table_text = ParagraphStyle(
        'TableText',
        parent=styles['Normal'],
        fontSize=10,
        leading=12
    )
    
    # Answer Key: Bold Green
    style_ans = ParagraphStyle(
        'AnswerKey',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.darkgreen,
        fontName='Helvetica-Bold',
        spaceBefore=8,
        spaceAfter=4
    )
    
    # Explanation: Normal Text (will be inside a grey box)
    style_exp = ParagraphStyle(
        'Explanation',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.black,
        alignment=0 # Left align
    )

    story = []
    
    # --- Title Page ---
    title = Paragraph("<b>Comprehensive Quiz Booklet</b>", styles['Title'])
    subtitle = Paragraph(f"Generated on Streamlit • {len(data)} Questions", styles['Normal'])
    story.append(title)
    story.append(subtitle)
    story.append(Spacer(1, 30))
    
    # --- Regex for "Match List" Detection ---
    # Captures: "A. Word" ... "- 1. Meaning"
    # Matches: Group 1=Letter, Group 2=Item, Group 3=Number, Group 4=Description
    match_pattern = re.compile(r"([A-Z])\.\s+(.*?)\s+-\s+(\d+)\.\s+(.*?)(?=\s[A-Z]\.| \Z|\Z)")

    for item in data:
        q_block = [] # We build the question block here
        
        # 1. Meta Data (ID & Source)
        meta_text = f"<b>Q{item['id']}</b>"
        if item.get('source'):
            meta_text += f" &nbsp;|&nbsp; {item['source']}"
        q_block.append(Paragraph(meta_text, style_meta))
        
        # 2. Question Text & Smart Table Detection
        q_text = item['question']
        
        # Run Regex to find "A. x - 1. y" pairs
        matches = match_pattern.findall(q_text)
        
        if matches and ("Match" in q_text or "List" in q_text):
            # --- TABLE MODE ---
            
            # Extract Intro Text (Everything before the first "A.")
            match_start = re.search(match_pattern, q_text).start()
            intro_text = q_text[:match_start].strip()
            
            # Add Intro Text
            q_block.append(Paragraph(intro_text, style_q))
            q_block.append(Spacer(1, 6))
            
            # Build Table Data
            # Header Row
            table_data = [[
                Paragraph("<b>List I</b>", style_table_text), 
                Paragraph("<b>List II</b>", style_table_text)
            ]]
            
            # Rows from Regex Matches
            for m in matches:
                # m = ('A', 'Talar', '1', 'Guard of Octroi')
                col1 = Paragraph(f"<b>{m[0]}.</b> {m[1]}", style_table_text)
                col2 = Paragraph(f"<b>{m[2]}.</b> {m[3]}", style_table_text)
                table_data.append([col1, col2])
            
            # Styling the Table
            t = Table(table_data, colWidths=[230, 230])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke), # Header BG
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),  # Grid lines
                ('VALIGN', (0,0), (-1,-1), 'TOP'),                # Top align
                ('PADDING', (0,0), (-1,-1), 6),                   # Padding
            ]))
            q_block.append(t)
            q_block.append(Spacer(1, 8))
            
        else:
            # --- NORMAL MODE ---
            q_block.append(Paragraph(q_text, style_q))
        
        # 3. Options
        options = item.get('options', {})
        if options:
            for key in sorted(options.keys()):
                opt_text = f"<b>({key})</b> {options[key]}"
                q_block.append(Paragraph(opt_text, style_opt))
        
        # 4. Answer Key
        ans_text = f"Correct Answer: {item['answer_key'].upper()}"
        q_block.append(Paragraph(ans_text, style_ans))
        
        # 5. Explanation Box (Elegant Grey Box)
        if item['explanation']:
            exp_content = [
                [Paragraph("<b>Explanation:</b>", style_opt)],
                [Paragraph(item['explanation'], style_exp)]
            ]
            
            # Create Table for Box effect
            # colWidths=[460] spans mostly full width (A4 is ~595pts, margins are 90 total)
            t_exp = Table(exp_content, colWidths=[460])
            t_exp.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8F9FA")), # Very light grey
                ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),             # Thin border
                ('PADDING', (0,0), (-1,-1), 8),                             # Internal padding
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ]))
            q_block.append(Spacer(1, 4))
            q_block.append(t_exp)
        
        # 6. Spacer & Divider
        q_block.append(Spacer(1, 15))
        q_block.append(Paragraph("_" * 80, style_meta)) # Thin separator line
        q_block.append(Spacer(1, 15))
        
        # 7. Add Block to Story (KeepTogether ensures no awkward page splits)
        story.append(KeepTogether(q_block))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# 3. STREAMLIT UI
# ==========================================
st.set_page_config(page_title="Smart Quiz Publisher", page_icon="📘", layout="centered")

st.title("📘 Smart Quiz Publisher")
st.markdown("""
**Transform your JSON data into a professional PDF.**
* Auto-maps Questions to Answers.
* Auto-formats 'Match the Column' questions into tables.
""")

st.write("---")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Questions File")
    q_file = st.file_uploader("Upload `questions.json`", type="json")

with col2:
    st.subheader("2. Answers File")
    a_file = st.file_uploader("Upload `answers.json`", type="json")

if q_file and a_file:
    if st.button("✨ Generate Booklet", type="primary"):
        with st.spinner("Analyzing and Designing PDF..."):
            
            # Step 1: Merge
            merged_data = merge_json_data(q_file, a_file)
            
            if merged_data:
                # Step 2: Create PDF
                pdf_bytes = create_elegant_pdf(merged_data)
                
                # Step 3: Success & Download
                st.success(f"Success! Processed {len(merged_data)} questions.")
                
                st.download_button(
                    label="📥 Download Professional PDF",
                    data=pdf_bytes,
                    file_name="Smart_Quiz_Booklet.pdf",
                    mime="application/pdf"
                )
            else:
                st.error("Merge failed. Please check if IDs match in both JSON files.")