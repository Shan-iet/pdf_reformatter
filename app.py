import streamlit as st
import pdfplumber
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO

# --- ROBUST LOGIC CLASS ---
class PDFQuizReformatter:
    def __init__(self, input_file):
        self.input_file = input_file
        self.questions = {}
        self.answers = {}
        self.explanations = {}
        self.debug_text = ""  # To store raw text for debugging
        
    def process(self):
        full_text = []
        tables = []
        
        with pdfplumber.open(self.input_file) as pdf:
            for i, page in enumerate(pdf.pages):
                # extract_text(layout=True) helps with columns, but standard is safer for now
                text = page.extract_text()
                if text:
                    full_text.append(text)
                
                # Extract tables for answer keys
                page_tables = page.extract_tables()
                if page_tables: tables.extend(page_tables)

        self.debug_text = "\n".join(full_text[:5]) # Store first 5 pages for debug view
        combined_text = "\n".join(full_text)
        
        if not combined_text.strip():
            return "EMPTY_TEXT_ERROR"

        # Try multiple regex patterns to see which one works best
        patterns = [
            re.compile(r'^\s*(\d+)\.\s+(.*)', re.DOTALL),      # Format: 1. Question
            re.compile(r'^\s*(\d+)\)\s+(.*)', re.DOTALL),      # Format: 1) Question
            re.compile(r'^\s*Q\.?\s*(\d+)[\.:]?\s+(.*)', re.DOTALL), # Format: Q.1. or Q1.
        ]
        
        best_count = 0
        best_pattern = None
        
        # Test which pattern finds the most questions
        for p in patterns:
            count = len(re.findall(p, combined_text, re.MULTILINE))
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
        
        # Robust Solution Regex (catches "Ans", "Solution", "Exp")
        sol_pattern = re.compile(r'^\s*(?:Solution|Ans|Exp|Correct Option).*?[:\s-]\s*\(?([a-d])\)?', re.IGNORECASE)
        # Specific "Question Number + Solution" regex (e.g., "8. Solution: (c)")
        numbered_sol_pattern = re.compile(r'^\s*(\d+)\.\s*(?:Solution|Ans|Exp).*?[:\s-]\s*\(?([a-d])\)?', re.IGNORECASE)

        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Matchers
            q_match = q_pattern.match(line)
            sol_match = sol_pattern.match(line)
            num_sol_match = numbered_sol_pattern.match(line)

            # Detect Answer Key Section (common keywords)
            if "ANSWER SHEET" in line.upper() or "ANSWER KEY" in line.upper():
                mode = "ANSWERS_SECTION"

            # CASE A: Numbered Solution (e.g. "55. Solution: (a)")
            if num_sol_match:
                q_id = int(num_sol_match.group(1))
                self.answers[q_id] = num_sol_match.group(2).upper()
                self.explanations[q_id] = line
                current_q_id = q_id
                mode = "IN_EXPLANATION"

            # CASE B: Inline Solution (e.g. "Ans: (a)") - applies to current question
            elif sol_match and current_q_id:
                self.answers[current_q_id] = sol_match.group(1).upper()
                self.explanations[current_q_id] = line
                mode = "IN_EXPLANATION"

            # CASE C: New Question Found
            elif q_match and mode != "ANSWERS_SECTION" and mode != "IN_EXPLANATION":
                if current_q_id and mode == "IN_QUESTION":
                    self.questions[current_q_id] = " ".join(buffer_text)
                
                current_q_id = int(q_match.group(1))
                buffer_text = [q_match.group(2)]
                mode = "IN_QUESTION"
                
            # CASE D: Reading Question Text
            elif mode == "IN_QUESTION":
                # Filter out obvious footers
                if "Page" in line or "ForumIAS" in line or "www." in line: continue
                buffer_text.append(line)
                
            # CASE E: Reading Explanation Text
            elif mode == "IN_EXPLANATION":
                if q_match: mode = "SCANNING" # Stop if we see new question
                else: self.explanations[current_q_id] += " " + line

        if current_q_id and mode == "IN_QUESTION":
            self.questions[current_q_id] = " ".join(buffer_text)

        # Parse Grid Tables (Economy Style)
        for table in tables:
            for row in table:
                flat_row = [str(x).strip() if x else "" for x in row]
                for i in range(0, len(flat_row) - 1):
                    # Look for [Number] -> [Letter]
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
            story.append(Paragraph("<b>No questions found yet.</b>", styles['Normal']))
            
        for q_id in sorted_ids:
            q_text = f"<b>Q{q_id}.</b> {self.questions[q_id]}"
            story.append(Paragraph(q_text, style_q))
            
            if q_id in self.answers:
                ans_text = f"<b>Answer: ({self.answers[q_id]})</b>"
                story.append(Paragraph(ans_text, style_ans))
            else:
                story.append(Paragraph("<b>Answer:</b> Not Found", style_ans))

            if q_id in self.explanations:
                exp_clean = self.explanations[q_id].replace(f"{q_id}.", "").strip()
                exp_text = f"<b>Explanation:</b> {exp_clean}"
                story.append(Paragraph(exp_text, style_exp))
            else:
                story.append(Spacer(1, 10))
            
            story.append(Spacer(1, 12))

        doc.build(story)
        output_buffer.seek(0)
        return output_buffer

# --- UI ---
st.set_page_config(page_title="PDF Quiz Fixer", page_icon="🔧")
st.title("🔧 Smart PDF Quiz Reformatter")

uploaded_file = st.file_uploader("Upload PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Process PDF"):
        processor = PDFQuizReformatter(uploaded_file)
        status = processor.process()
        
        if status == "SUCCESS":
            st.success(f"Success! Found {len(processor.questions)} questions.")
            pdf_bytes = processor.generate_pdf_bytes()
            st.download_button("Download Result", pdf_bytes, "fixed_quiz.pdf", "application/pdf")
            
        elif status == "EMPTY_TEXT_ERROR":
            st.error("⚠️ Error: No text found. This PDF seems to be SCANNED images.")
            st.info("Solution: Use a PDF OCR tool (like Adobe or online OCR) to convert it to text first.")
            
        elif status == "NO_QUESTIONS_MATCHED":
            st.error("⚠️ Error: 0 Questions found.")
            st.warning("The code couldn't find patterns like '1. Question' or '1) Question'.")
            
            # --- DEBUGGER ---
            with st.expander("See what the computer sees (Debug View)"):
                st.write("Check if the text below looks correct or messy:")
                st.text(processor.debug_text)