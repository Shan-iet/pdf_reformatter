import streamlit as st
import pdfplumber
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

# --- THE LOGIC CLASS ---
class PDFQuizReformatter:
    def __init__(self, input_file):
        self.input_file = input_file
        self.questions = {}
        self.answers = {}
        self.explanations = {}
        
        # Regex to find "1. Question text..."
        self.q_pattern = re.compile(r'^\s*(\d+)\.\s+(.*)', re.DOTALL)
        # Regex to find "1. Solution: (a)..."
        self.sol_pattern = re.compile(r'^\s*(\d+)\.\s*(?:Solution|Ans|Exp|Correct Option).*?:\s*\(?([a-d])\)?', re.IGNORECASE)

    def process(self):
        full_text = []
        tables = []
        
        # Read the uploaded PDF
        with pdfplumber.open(self.input_file) as pdf:
            for page in pdf.pages:
                # Extract text
                text = page.extract_text()
                if text: full_text.append(text)
                
                # Extract tables (for answer keys at the end)
                page_tables = page.extract_tables()
                if page_tables: tables.extend(page_tables)
        
        combined_text = "\n".join(full_text)
        self._parse_content(combined_text, tables)

    def _parse_content(self, text, tables):
        lines = text.split('\n')
        current_q_id = None
        buffer_text = []
        mode = "SCANNING" 
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            q_match = self.q_pattern.match(line)
            sol_match = self.sol_pattern.match(line)

            # Detect if we reached the answer key section
            if "ANSWER SHEET" in line or "Explanatory Notes" in line:
                mode = "ANSWERS_SECTION"

            # CASE A: We found a written solution (History PDF style)
            if sol_match:
                q_id = int(sol_match.group(1))
                self.answers[q_id] = sol_match.group(2).upper()
                self.explanations[q_id] = line 
                current_q_id = q_id
                mode = "IN_EXPLANATION"
                
            # CASE B: We found a new question
            elif q_match and mode != "ANSWERS_SECTION" and mode != "IN_EXPLANATION":
                # Save the previous question before starting new one
                if current_q_id and mode == "IN_QUESTION":
                    self.questions[current_q_id] = " ".join(buffer_text)
                
                current_q_id = int(q_match.group(1))
                buffer_text = [q_match.group(2)]
                mode = "IN_QUESTION"
                
            # CASE C: We are reading a question
            elif mode == "IN_QUESTION":
                if "Page" in line or "Forum AS" in line: continue # Skip footers
                buffer_text.append(line)
                
            # CASE D: We are reading an explanation
            elif mode == "IN_EXPLANATION":
                if q_match: mode = "SCANNING" # Stop if we see a new number
                else: self.explanations[current_q_id] += " " + line

        # Save the very last question
        if current_q_id and mode == "IN_QUESTION":
            self.questions[current_q_id] = " ".join(buffer_text)

        # CASE E: We parse the Grid Tables (Economy PDF style)
        for table in tables:
            for row in table:
                # Flatten row and clean data
                flat_row = [str(x).strip() if x else "" for x in row]
                for i in range(0, len(flat_row) - 1):
                    # Look for pattern: [Number] followed by [A/B/C/D]
                    if flat_row[i].isdigit() and flat_row[i+1].upper() in ['A','B','C','D']:
                        try:
                            q_id = int(flat_row[i])
                            self.answers[q_id] = flat_row[i+1].upper()
                        except ValueError: continue

    def generate_pdf_bytes(self):
        output_buffer = BytesIO()
        doc = SimpleDocTemplate(output_buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        
        style_q = ParagraphStyle('Question', parent=styles['Normal'], fontSize=11, spaceAfter=6, leading=14)
        style_ans = ParagraphStyle('Answer', parent=styles['Normal'], fontSize=10, textColor=colors.darkblue, spaceAfter=2)
        style_exp = ParagraphStyle('Explanation', parent=styles['Normal'], fontSize=10, textColor=colors.darkgreen, leftIndent=20, spaceAfter=12)
        
        story = []
        sorted_ids = sorted(self.questions.keys())
        
        if not sorted_ids:
            story.append(Paragraph("<b>Error:</b> No questions were detected.", styles['Normal']))
            story.append(Paragraph("Make sure questions start with '1. ', '2. ' etc.", styles['Normal']))
        
        for q_id in sorted_ids:
            # Add Question
            q_text = f"<b>Q{q_id}.</b> {self.questions[q_id]}"
            story.append(Paragraph(q_text, style_q))
            
            # Add Answer
            if q_id in self.answers:
                ans_text = f"<b>Answer: ({self.answers[q_id]})</b>"
                story.append(Paragraph(ans_text, style_ans))
            else:
                story.append(Paragraph("<b>Answer:</b> Not Found", style_ans))

            # Add Explanation
            if q_id in self.explanations:
                # Clean up the explanation text slightly
                exp_clean = self.explanations[q_id].replace(f"{q_id}.", "").strip()
                exp_text = f"<b>Explanation:</b> {exp_clean}"
                story.append(Paragraph(exp_text, style_exp))
            else:
                story.append(Spacer(1, 10))
            
            story.append(Spacer(1, 12))

        doc.build(story)
        output_buffer.seek(0)
        return output_buffer

# --- THE WEBSITE UI ---
st.set_page_config(page_title="PDF Quiz Reformatter", page_icon="📚")
st.title("📚 PDF Quiz Reformatter")
st.markdown("""
Upload a PDF containing MCQs. 
This tool will rearrange them so the **Answer & Explanation appear immediately below each Question.**
""")

uploaded_file = st.file_uploader("Upload your PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Process PDF"):
        with st.spinner("Reading file... (this may take a moment)"):
            try:
                processor = PDFQuizReformatter(uploaded_file)
                processor.process()
                
                pdf_bytes = processor.generate_pdf_bytes()
                
                st.success(f"Done! Found {len(processor.questions)} questions.")
                
                st.download_button(
                    label="📥 Download Reformatted PDF",
                    data=pdf_bytes,
                    file_name="reformatted_quiz.pdf",
                    mime="application/pdf"
                )
            except Exception as e:
                st.error(f"Something went wrong: {e}")