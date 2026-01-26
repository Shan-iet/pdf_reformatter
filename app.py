import streamlit as st
import pdfplumber
import pypdf
import re
import io  # <--- Added this
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

# --- CORE LOGIC CLASS ---
class PDFQuizReformatter:
    def __init__(self, input_file):
        # We read the bytes ONCE and store them.
        # This prevents "file closed" errors when switching libraries.
        self.file_bytes = input_file.getvalue()
        
        self.questions = {}     
        self.answers = {}       
        self.explanations = {}  
        self.debug_text = ""    
        
    def process(self):
        full_text = []
        tables = []
        
        # --- ATTEMPT 1: PDFPLUMBER (Best for Tables) ---
        try:
            # Create a fresh stream for pdfplumber
            with pdfplumber.open(io.BytesIO(self.file_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: full_text.append(text)
                    
                    page_tables = page.extract_tables()
                    if page_tables: tables.extend(page_tables)
        except Exception as e:
            print(f"Primary reader error: {e}")

        combined_text = "\n".join(full_text)

        # --- ATTEMPT 2: PYPDF (Backup for weird fonts) ---
        # If pdfplumber failed to get text, we try pypdf with a FRESH stream
        if not combined_text.strip():
            st.warning("⚠️ Primary reader found no text. Switching to Backup Engine (pypdf)...")
            full_text = []
            try:
                # Create a NEW fresh stream for pypdf
                backup_stream = io.BytesIO(self.file_bytes)
                reader = pypdf.PdfReader(backup_stream)
                for page in reader.pages:
                    text = page.extract_text()
                    if text: full_text.append(text)
                combined_text = "\n".join(full_text)
            except Exception as e:
                return f"BACKUP_FAILED: {e}"

        self.debug_text = combined_text[:1000] 
        
        if not combined_text.strip():
            return "EMPTY_TEXT_ERROR"

        # --- SMART PATTERN DETECTION ---
        patterns = [
            # Pattern A: "1. Question..." (Most common)
            re.compile(r'^\s*(\d+)\.\s+(.*)', re.DOTALL | re.MULTILINE),
            # Pattern B: "1) Question..."
            re.compile(r'^\s*(\d+)\)\s+(.*)', re.DOTALL | re.MULTILINE),
            # Pattern C: "Q.1 Question..."
            re.compile(r'^\s*Q\.?\s*(\d+)[\.:]?\s+(.*)', re.DOTALL | re.MULTILINE),
             # Pattern D: Simple Number start "1 " (Risky but catches loose formats)
            re.compile(r'^\s*(\d+)\s+(.*)', re.DOTALL | re.MULTILINE),
        ]
        
        best_count = 0
        best_pattern = None
        
        for p in patterns:
            # Use p.findall directly without flags
            count = len(p.findall(combined_text))
            if count > best_count:
                best_count = count
                best_pattern = p
        
        if best_count == 0:
            return "NO_QUESTIONS_MATCHED"
            
        self._parse_content(combined_text, tables, best_pattern)
        return "SUCCESS"

    def _parse_content(self, text, tables, q_pattern):
        lines = text.split('\n')
        current_q_id = None
        buffer_text = []
        mode = "SCANNING"
        
        # Regex to find solutions like "Solution: (a)" or "Ans. (b)"
        sol_pattern = re.compile(r'^\s*(?:Solution|Ans|Exp|Correct Option).*?[:\s-]\s*\(?([a-d])\)?', re.IGNORECASE)
        # Regex for numbered solutions "8. Solution: (c)"
        numbered_sol_pattern = re.compile(r'^\s*(\d+)\.\s*(?:Solution|Ans|Exp).*?[:\s-]\s*\(?([a-d])\)?', re.IGNORECASE)

        for line in lines:
            line = line.strip()
            if not line: continue
            
            q_match = q_pattern.match(line)
            sol_match = sol_pattern.match(line)
            num_sol_match = numbered_sol_pattern.match(line)

            # Detect Answer Key Sections
            if "ANSWER SHEET" in line.upper() or "ANSWER KEY" in line.upper() or "EXPLANATORY NOTES" in line.upper():
                mode = "ANSWERS_SECTION"

            # Case 1: Numbered Solution (e.g. "55. Solution: (a)")
            if num_sol_match:
                q_id = int(num_sol_match.group(1))
                self.answers[q_id] = num_sol_match.group(2).upper()
                self.explanations[q_id] = line
                current_q_id = q_id
                mode = "IN_EXPLANATION"

            # Case 2: Inline Solution (e.g. "Ans: (a)")
            elif sol_match and current_q_id:
                self.answers[current_q_id] = sol_match.group(1).upper()
                self.explanations[current_q_id] = line
                mode = "IN_EXPLANATION"

            # Case 3: New Question
            elif q_match and mode != "IN_EXPLANATION":
                if current_q_id and mode == "IN_QUESTION":
                    self.questions[current_q_id] = " ".join(buffer_text)
                current_q_id = int(q_match.group(1))
                buffer_text = [q_match.group(2)]
                mode = "IN_QUESTION"
                
            # Case 4: Continued Question
            elif mode == "IN_QUESTION":
                if "Page" in line or "ForumIAS" in line or "www." in line: continue
                buffer_text.append(line)
                
            # Case 5: Continued Explanation
            elif mode == "IN_EXPLANATION":
                if q_match: 
                    if current_q_id and mode == "IN_QUESTION":
                         self.questions[current_q_id] = " ".join(buffer_text)
                    current_q_id = int(q_match.group(1))
                    buffer_text = [q_match.group(2)]
                    mode = "IN_QUESTION"
                else:
                    self.explanations[current_q_id] += " " + line

        if current_q_id and mode == "IN_QUESTION":
            self.questions[current_q_id] = " ".join(buffer_text)

        # Parse Grid Tables
        for table in tables:
            for row in table:
                flat_row = [str(x).strip() if x else "" for x in row]
                for i in range(0, len(flat_row) - 1):
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
            story.append(Paragraph("<b>No questions found.</b> Check Debug View.", styles['Normal']))
            
        for q_id in sorted_ids:
            q_text = f"<b>Q{q_id}.</b> {self.questions[q_id]}"
            story.append(Paragraph(q_text, style_q))
            
            if q_id in self.answers:
                ans_text = f"<b>Answer: ({self.answers[q_id]})</b>"
                story.append(Paragraph(ans_text, style_ans))
            else:
                story.append(Paragraph("<b>Answer:</b> Not Found", style_ans))

            if q_id in self.explanations:
                exp_clean = self.explanations[q_id].replace(f"{q_id}.", "", 1).strip()
                exp_text = f"<b>Explanation:</b> {exp_clean}"
                story.append(Paragraph(exp_text, style_exp))
            else:
                story.append(Spacer(1, 10))
            
            story.append(Spacer(1, 12))

        doc.build(story)
        output_buffer.seek(0)
        return output_buffer

# --- UI ---
st.set_page_config(page_title="PDF Quiz Reformatter", page_icon="📝")
st.title("📝 PDF Quiz Reformatter")
st.markdown("Upload a PDF. I will stack Questions, Answers, and Explanations together.")

uploaded_file = st.file_uploader("Upload PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Process PDF"):
        with st.spinner("Processing..."):
            try:
                # Pass the file directly
                processor = PDFQuizReformatter(uploaded_file)
                status = processor.process()
                
                if status == "SUCCESS":
                    st.success(f"Success! Found {len(processor.questions)} questions.")
                    pdf_bytes = processor.generate_pdf_bytes()
                    st.download_button(label="📥 Download Result", data=pdf_bytes, file_name="reformatted_quiz.pdf", mime="application/pdf")
                    
                elif status == "EMPTY_TEXT_ERROR":
                    st.error("⚠️ Error: No text found (Scanned?).")
                    
                elif status == "NO_QUESTIONS_MATCHED":
                    st.error("⚠️ Error: 0 Questions found.")
                    with st.expander("Debug View"):
                        st.text(processor.debug_text)
                        
            except Exception as e:
                st.error(f"An error occurred: {e}")