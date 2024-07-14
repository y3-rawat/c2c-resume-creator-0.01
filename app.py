import logging
from typing import Dict, Any, List, Tuple
from flask import Flask, request, render_template, redirect, url_for, flash, session
import os
from langchain_community.document_loaders import PyPDFLoader
import apis as a
import re
import tempfile
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from prompt import profile_generator_experience, profile_generator_prompt_no_experience

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

pdf_prompt = """
You have to find these things from the resume 

Basic Information
Full Name
Contact Information:
Phone Number
Email Address
Address (if available)
LinkedIn Profile (if available)
Personal Website or Portfolio (if available)
Professional Summary or Objective

Education
Degree(s) Obtained
Field(s) of Study
Institution(s) Attended
Graduation Date(s)
Academic Achievements or Honors

Work Experience
Job Title(s)
Company Name(s)
Location(s)
Employment Dates
Key Responsibilities and Achievements
Technologies and Tools Used

Skills
Technical Skills
Soft Skills
Certifications and Licenses

Projects
Project Title(s)
Description of Projects
Technologies and Tools Used
Role in the Project

Awards and Honors
Award Title(s)
Issuing Organization
Date of Award

Professional Development
Certifications
Training Programs
Workshops and Seminars

Publications and Research
Publication Titles
Journal or Conference Name
Date of Publication
Co-authors (if any)

Professional Affiliations
Membership in Professional Organizations
Leadership Roles in Professional Organizations

Languages
Languages Known
Proficiency Level

References
Reference Name(s)
Contact Information
Relationship to the Candidate

Additional Sections
Volunteer Experience
Hobbies and Interests
Personal Projects
Additional Information Relevant to the Job
"""

def ques(user_resume: str, job_description: str, work: str) -> str:
    return f"""
    You're an AI with a talent for crafting thoughtful prompts to extract necessary details from users for creating tailored resumes. Your task is to ask the user for three specific questions based on their provided resume, job description, and additional work information to generate a new resume.
    -----
        user_resume = {user_resume}
        ----
        job_description = {job_description}
        ----
        additional_work = {work}
        ----

    Please ask the user three questions that will help you create a customized and effective resume based on the information provided. Remember to consider the user's skills, experience, and the specific requirements of the job role outlined in the job description. This will ensure that the new resume you generate is a perfect fit for the user's desired position. questions should be sprated by | 
    example of format -> **question1** ** question2**  **question3 **
    """

def extract_between_asterisks(text: str) -> List[str]:
    pattern = r'\*\*(.*?)\*\*'
    return re.findall(pattern, text)

def input_pdf_setup(uploaded_file) -> Tuple[str, str]:
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_file.filename)
    uploaded_file.save(filepath)
    loader = PyPDFLoader(file_path=filepath)
    pages = loader.load_and_split()
    if len(pages) < 1:
        raise ValueError("The PDF file has no pages.")
    text = " ".join([page.page_content for page in pages])
    content = f"{pdf_prompt} here is the content of resume {text}"
    return a.final(content), filepath

def save_to_temp_file(data: Any) -> str:
    with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8') as temp_file:
        json.dump(data, temp_file, ensure_ascii=False)
    return temp_file.name

def load_from_temp_file(file_path: str) -> Any:
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def run_prompts_in_parallel(*prompts: str) -> Dict[str, Any]:
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(prompts), os.cpu_count() or 1)) as executor:
        future_to_prompt = {executor.submit(process_prompt, prompt): prompt for prompt in prompts}
        for future in as_completed(future_to_prompt):
            prompt = future_to_prompt[future]
            try:
                result = future.result()
            except Exception as exc:
                logging.error(f"Error processing prompt: {exc}")
                result = {"error": str(exc)}
            results[prompt] = result
    return results

def process_prompt(prompt: str) -> Dict[str, Any]:
    try:
        result = a.final(prompt)
        return json.loads(result)
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                return {"error": "Failed to parse JSON from response"}
        else:
            return {"error": "No valid JSON found in response"}
        

@app.route('/', methods=['GET', 'POST'])
def index():
    print("-2")
    if request.method == 'POST':
        print("post1")
        file = request.files.get('file-upload')
        print("post2")
        job_description = request.form.get('jobDescription')
        print("post3")
        experience = request.form.get('experience')
        additional_info = request.form.get('additionalInfo')
        print('done1')
        if not experience:
            flash('Please select an experience level.', 'error')
            return render_template('index.html', job_description=job_description, additional_info=additional_info)

        if not job_description:
            flash('Job description is required.', 'error')
            return render_template('index.html', job_description=job_description, additional_info=additional_info)

        if file and file.filename.endswith('.pdf'):
            try:
                print('done2')
                extracted_data, file_path = input_pdf_setup(file)
                extracted_data_file = save_to_temp_file(extracted_data)
                session['extracted_data_file'] = extracted_data_file
                session['job_description'] = job_description
                session['experience'] = experience
                session['additional_info'] = additional_info
                session['file_path'] = file_path
                print('done3')
                question = ques(extracted_data, job_description, additional_info)
                q = a.final(question)
                print('done4')
                questions = extract_between_asterisks(q)
                print('done5')
                questions_file = save_to_temp_file(questions)
                print('done5.9')
                session['questions_file'] = questions_file
                print('done6')
                
                return redirect(url_for('questionnaire', step=1))
            except Exception as e:
                flash(str(e), 'error')
                return render_template('index.html', job_description=job_description, additional_info=additional_info)
        else:
            flash('Please upload a PDF file.', 'error')
    
    return render_template('index.html')

@app.route('/questionnaire/<int:step>', methods=['GET', 'POST'])
def questionnaire(step: int):
    inputs = session.get('inputs', {})
    questions_file = session.get('questions_file')
    questions = load_from_temp_file(questions_file)

    if request.method == 'POST':
        inputs[f'input{step}'] = request.form.get('input_value')
        session['inputs'] = inputs
        if step < len(questions):
            return redirect(url_for('questionnaire', step=step + 1))
        else:
            return redirect(url_for('result'))
    
    if step > len(questions):
        return redirect(url_for('result'))
    
    question = questions[step - 1] if questions else "No question available"
    return render_template('input_step.html', step=step, question=question, inputs=inputs, questions=questions)

@app.route('/result')
def result():
    try:
        # Retrieve data from session
        extracted_data = load_from_temp_file(session.get('extracted_data_file'))
        job_description = session.get('job_description', '')
        experience = session.get('experience', 'No Experience')
        additional_info = session.get('additional_info', '')
        inputs = session.get('inputs', {})
        questions = load_from_temp_file(session.get('questions_file'))

        # Prepare other questions
        other_questions = {questions[i]: inputs.get(f'input{i+1}', '') for i in range(len(questions))}
        
        # Determine if user has experience
        has_experience = experience.lower() == "experience"

        # Generate prompts based on experience
        generator_func = profile_generator_experience if has_experience else profile_generator_prompt_no_experience
        prompts = generator_func(extracted_data, job_description, additional_info, other_questions)

        # Run prompts in parallel
        results = run_prompts_in_parallel(*prompts)

        # Prepare data for template
        template_data = {
            'job_description': job_description,
            'profile_creator_result': results.get(prompts[0], {}),
            'technical_skills_result': results.get(prompts[1], {}),
            'soft_skills_result': results.get(prompts[2], {}),
            'project_result': results.get(prompts[-1], {}),
            'experience_result': results.get(prompts[3], {}) if has_experience else {}
        }

        return render_template('result.html', **template_data)

    except Exception as e:
        logging.error(f"Error in result route: {str(e)}", exc_info=True)
        flash(f"An error occurred: {str(e)}", 'error')
        return redirect(url_for('index'))


@app.route('/edit/<int:step>')
def edit_input(step: int):
    return redirect(url_for('questionnaire', step=step))

if __name__ == '__main__':
    print("start")
    app.run(debug=True, port=3313)