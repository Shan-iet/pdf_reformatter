import streamlit as st
import pdfplumber
import re
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

class PDFQuizReformatter:
    def __init__(self, input_file):
        self.file_bytes = input_file.getvalue()
        self.questions = {}
        self.answers = {}
        self.explanations = {}
        self.debug_text = ""
        
    def _extract_text_smart(self, page):
        """
        Splits page into Left/Right columns to prevent merging text.
        Returns combined text: Left Column \n Right Column
        """
        width = page.width
        height = page.height
        
        # 1. Define Crop Boxes (Left Half / Right Half)
        # We assume a small margin in the center (45% to 55%) to avoid cutting words
        left_bbox = (0, 0, width * 0.55, height)
        right_bbox = (width * 0.45, 0, width, height)
        
        try:
            # Crop and extract left
            left_crop = page.crop(left_bbox)
            left_text = left_crop.extract_text(layout=False) or ""
            
            # Crop and extract right
            right_crop = page.crop(right_bbox)
            right_text = right_crop.extract_text(layout=False) or ""
            
            return left_text + "\n" + right_text
        except Exception:
            # Fallback if cropping fails (e.g. weird page size)
            return page.extract_text() or ""

    def process(self):
        full_text_list = []
        tables = []
        
        # --- 1. READ WITH COLUMN AWARENESS ---
        with pdfplumber.open(io.BytesIO(self.file_bytes)) as pdf:
            for page in pdf.pages:
                # Extract text using the "Split Columns" strategy
                text = self._extract_text_smart(page)
                
                # CLEANING: Remove headers/footers commonly found in UPSC PDFs
                lines = text.split('\n')
                cleaned_lines = []
                for line in lines:
                    # Filter junk lines
                    if len(line) < 4 and not line[0].isdigit(): continue
                    if "ForumIAS" in line or "Page" in line or "PYQ Workbook" in line: continue
                    if "Vivek Singh" in line or "ECO-550" in line: continue
                    cleaned_lines.append(line)
                
                full_text_list.append("\n".join(cleaned_lines))
                
                # Extract Tables (for Grid Answer Keys)
                tables.extend(page.extract_tables())

        combined_text = "\n".join(full_text_list)
        self.debug_text = combined_text[:2000] # Save for user to see

        if not combined_text.strip():
            return "EMPTY_TEXT_ERROR"

        # --- 2. FIND ALL QUESTIONS (REGEX BLOCK) ---
        # Instead of line-by-line, we search the whole blob for "Number. " pattern
        # This handles multi-line questions perfectly.
        
        # Regex: Look for newline + number + dot/bracket + space
        # e.g. "\n1. " or "\n25. " or "\nQ1. "
        split_pattern = re.compile(r'\n\s*(?:Q\.?)?(\d+)[\.\)]\s+')
        
        # Split text by this pattern. 
        # Result: [Junk, "1", "Question Text...", "2", "Question Text..."]
        segments = split_pattern.split('\n' + combined_text)
        
        if len(segments) < 2:
            return "NO_QUESTIONS_MATCHED"

        # --- 3. PARSE SEGMENTS ---
        # Segments[0] is intro text. Then Segments[1]=ID, Segments[2]=Text, Segments[3]=ID...
        for i in range(1, len(segments), 2):
            try:
                q_id = int(segments[i])
                content = segments[i+1].strip()
                
                # SEPARATE QUESTION FROM SOLUTION (if inline)
                # Look for "Solution: (a)" or "Ans. (b)" inside the content
                sol_match = re.search(r'(?:\n|\s)(?:Solution|Ans|Exp|Correct Option|Answer).*?[:\s-]\s*\(?([a-d])\)?', content, re.IGNORECASE)
                
                if sol_match:
                    # We found a solution INSIDE this block
                    ans_char = sol_match.group(1).upper()
                    
                    # Split Question Text and Explanation Text
                    split_idx = sol_match.start()
                    q_text = content[:split_idx].strip()
                    exp_text = content[split_idx:].strip()
                    
                    self.questions[q_id] = q_text
                    self.answers[q_id] = ans_char
                    self.explanations[q_id] = exp_text
                else:
                    # No inline solution, just a question (Answer might be in grid table later)
                    self.questions[q_id] = content
            except ValueError:
                continue

        # --- 4. PARSE GRID TABLES (For Economy PDF) ---
        for table in tables:
            for row in table:
                flat_row = [str(x).strip().upper() if x else "" for x in row]
                for i in range(0, len(flat_row) - 1):
                    # Check for "51" -> "A"
                    if flat_row[i].isdigit() and flat_row[i+1] in ['A','B','C','D']:
                        q_id = int(flat_row[i])
                        # Only overwrite if we didn't find an inline answer already
                        if q_id not in self.answers:
                            self.answers[q_id] = flat_row[i+1]
        
        return "SUCCESS"

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
            story.append(Paragraph("<b>No questions found.</b>", styles['Normal']))
            
        for q_id in sorted_ids:
            # Question
            q_text = f"<b>Q{q_id}.</b> {self.questions[q_id]}"
            story.append(Paragraph(q_text, style_q))
            
            # Answer
            if q_id in self.answers:
                ans_text = f"<b>Answer: ({self.answers[q_id]})</b>"
                story.append(Paragraph(ans_text, style_ans))
            else:
                story.append(Paragraph("<b>Answer:</b> Not Found (Check end of PDF for key)", style_ans))

            # Explanation
            if q_id in self.explanations:
                # Clean up "Solution: (a)" from start of explanation to look nice
                raw_exp = self.explanations[q_id]
                clean_exp = re.sub(r'^(?:Solution|Ans|Exp).*?[:\s-]\s*\(?[a-d]\)?', '', raw_exp, flags=re.IGNORECASE).strip()
                
                exp_text = f"<b>Explanation:</b> {clean_exp}"
                story.append(Paragraph(exp_text, style_exp))
            else:
                story.append(Spacer(1, 10))
            
            story.append(Spacer(1, 12))

        doc.build(story)
        output_buffer.seek(0)
        return output_buffer

# --- UI ---
st.set_page_config(page_title="PDF Quiz Reformatter", page_icon="📝")
st.title("📝 PDF Quiz Reformatter (Robust Mode)")
st.markdown("""
**New Feature:** Two-Column Support.  
If your PDF has two columns (like ForumIAS), I will now read it correctly.
""")

uploaded_file = st.file_uploader("Upload PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Process PDF"):
        with st.spinner("Processing (Splitting Columns)..."):
            try:
                processor = PDFQuizReformatter(uploaded_file)
                status = processor.process()
                
                if status == "SUCCESS":
                    st.success(f"Success! Found {len(processor.questions)} questions.")
                    pdf_bytes = processor.generate_pdf_bytes()
                    st.download_button(label="📥 Download Result", data=pdf_bytes, file_name="reformatted_quiz.pdf", mime="application/pdf")
                
                elif status == "NO_QUESTIONS_MATCHED":
                    st.error("⚠️ Found 0 questions.")
                    st.warning("Check the Debug View below. If text looks garbled, the PDF might be encrypted.")
                    with st.expander("Debug Text View"):
                        st.text(processor.debug_text)
                        
                elif status == "EMPTY_TEXT_ERROR":
                    st.error("⚠️ PDF is empty or scanned images.")
                    
            except Exception as e:
                st.error(f"An error occurred: {e}")