#!/usr/bin/env python
# coding: utf-8

# ## Auto-IEP

# > Install required libraries

# In[1]:

# >Import required libraries

# In[2]:


import os
import sys
import re
import numpy as np
import pandas as pd
import docx2txt
from docx import Document
import requests
import json
import  tkinter as tk
from tkinter import filedialog, ttk
import threading

# > API key for openai call, removed if being sent for outside viewing

API_KEY = "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"


# > Function definition for test selection
def file_select_WCJ():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title = "Select a WCJ File")
    return file_path
# In[4]:

# >Function definition for handling WCJ test reports

# In[6]:

def handle_WCJ_test_files(selected_file):
    #Convert student file to tables
    doc = Document(selected_file)
    tables = doc.tables

    #Turn tables into dataframe
    def table_to_df(table):
        data = []
        for row in table.rows:
            data.append([cell.text for cell in row.cells])
        df = pd.DataFrame(data)
        df.columns = df.iloc[0]
        df = df.drop(0)
        return df
    dataframes = [table_to_df(table) for table in tables]


    # Extract the text from the document
    text = [p.text for p in doc.paragraphs if p.text.strip() != ""]

    # Extract the score ranges and classifications
    data = []
    for line in text:
        # Search for lines that contain a score range and a classification
        match = re.search(r'(\d+ and [a-zA-Z]+|\d+ to \d+)\s*(.*)', line)
        if match:
            score_range = match.group(1)
            classification = match.group(2)
            data.append((score_range, classification))

    # Create a DataFrame for Score Ranges
    df_scoreranges = pd.DataFrame(data, columns=['Standard Score (SS) Range', 'WJIV Classification'])

    #Flag for having run the basic data transformer
    ran = False

    #Data transformer for basic info, name, dob etc.
    for dataframe in dataframes:
        if 'Name: ' in dataframe.columns[0] and ran == False:
            data = {
                'Name': [dataframe.columns[0].split(':')[1].strip()],
                'DOB': [dataframe.iloc[0, 0].split(':')[1].strip()],
                'Sex': [dataframe.iloc[2, 0].split(':')[1].strip()],
                'ID': [dataframe.iloc[2, 1].split('ID:')[1].strip()]
            }
            dataframenew = pd.DataFrame(data)
            ran = True
            
    #Saving real student name in a string so it can be placed into final response
    dataframes[0] = dataframenew
    REALSTUDENTNAME = dataframes[0].iloc[0,0].split(', ')[1].strip()

    #Function to convert score ranges to integers
    def convert_range_to_integers(score_range):
        if 'and above' in score_range:
            return [int(score_range.split(' ')[0]), float('inf')]
        elif 'and Below' in score_range:
            return [float('-inf'), int(score_range.split(' ')[0])]
        else:
            return [int(x) for x in score_range.split(' to ')]

    #Apply the function to the dataframe
    df_scoreranges['Score Range'] = df_scoreranges['Standard Score (SS) Range'].apply(convert_range_to_integers)

    #Adding a proficiency column for scores
    def get_proficiency(score):
        for index, row in df_scoreranges.iterrows():
           if not score == '' and row['Score Range'][0] <= int(score) <= row['Score Range'][1]:
                return row['WJIV Classification']
        return 'Unknown'
    proficiency_dfs = []
    for i, dataframe in enumerate(dataframes):
        if 'Cluster' in dataframes[i].columns:
            dataframes[i]['Proficiency'] = dataframes[i]['Current Scores'].apply(get_proficiency)
            proficiency_dfs.append(dataframes[i])
    allScores = pd.concat(proficiency_dfs)
    allScores = allScores[allScores['Proficiency'] != 'Unknown']
    allScores = allScores.reindex(axis = 0)

    #Creating a sentences list for our prompt, starting with test proficiencies
    student_name = "Placeholder"
    sentences = []
    for index, row in allScores.iterrows():
        subject_area = row['Cluster']
        proficiency = row['Proficiency']
        sentence = f"{student_name} has {proficiency} proficiency in {subject_area}."
        sentences.append(sentence)

    #QUALITATIVE OBS added to sentences
    observations_dfs = []
    for i, dataframe in enumerate(dataframes):
        if 'Woodcock-Johnson IV Tests of Achievement Form A and Extended Qualitative Observations' in dataframes[i].columns:
            observations_dfs.append(dataframes[i])
    observations = pd.concat(observations_dfs, ignore_index=True)
    observations = observations.iloc[:, 1]
    observations = observations.to_frame()
    observations = observations.reindex(axis = 0)
    for index, row in observations.iterrows():
        comment = row['Woodcock-Johnson IV Tests of Achievement Form A and Extended Qualitative Observations'] 
        sentence = f"In regards to {comment}"
        #Replaces student name FERPA
        sentence = sentence.replace(REALSTUDENTNAME, "Placeholder")
        sentences.append(sentence)

    #TEST OBS added to sentences
    observations_dfstest = []
    for i, dataframe in enumerate(dataframes):
        if 'Woodcock-Johnson IV Tests of Achievement Form A and Extended Test Session Observations' in dataframes[i].columns:
            observations_dfstest.append(dataframes[i])
    observations = pd.concat(observations_dfstest, ignore_index=True)
    observations = observations.iloc[:, 1]
    observations = observations.to_frame()
    observations = observations.reindex(axis = 0)
    for index, row in observations.iterrows():
        comment = row['Woodcock-Johnson IV Tests of Achievement Form A and Extended Test Session Observations'] 
        sentence = f"In regards to {comment}."
        #Replaces student name FERPA
        sentence = sentence.replace(REALSTUDENTNAME, "Placeholder")
        sentences.append(sentence)

    #Joining sentences for use in prompt
    dataForPrompt = ' '.join(map(str, sentences))

    #Tuning our input for best results
    promptTuning = """Write an academic assesment report based on the following data collected 
    from the Woodcock-Johnson IV Tests of Achievement, make it do not make it flowery and also understand this student 
    is in special education. 
    Be sure to highlight relative strengths, also do not write in all caps. 
    Avoid using run on sentences, try not to combine multiple subject areas into one sentence.
    Be certain to provide specific details. 
    Be cautious to avoid any kind of linguistic mistakes.
    Do not make special mention of referring to the student as Placeholder, treat it as a name.
    Data: """

    #Beginning of AI script
    API_ENDPOINT = "https://api.openai.com/v1/chat/completions"
    
    #Openai interaction function
    def generate_chat_completion(messages, model="gpt-4", temperature=1, max_tokens=None):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }

        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            data["max_tokens"] = max_tokens

        response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(data))

        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            raise Exception(f"Error {response.status_code}: {response.text}")
    
    #The prompt we pass to gpt
    PROMPT = ( f"{promptTuning}{dataForPrompt}")
    
    #Define how gpt should act
    messages=[
        {"role": "system", "content": "You are a special education teacher"},
        {"role": "user", "content": (f"{PROMPT}")},
    ]
    #Call and get response
    response_text = generate_chat_completion(messages)
    #Replace placeholder with real student name
    #Due to FERPA considerations this may be commented out to keep the placeholder name for outside viewing
    response_text = response_text.replace("Placeholder", REALSTUDENTNAME)
    return (response_text)


# > Solicit user interaction and run program

# In[ ]:

def on_api_call_complete():
    # Hide the progress bar and spinner label
    progress.pack_forget()
    spinner_label.pack_forget()

    # Display the report in the root window
    text_widget = tk.Text(root, wrap=tk.WORD)
    text_widget.insert(tk.END, response_text)
    text_widget.pack(expand=1, fill="both")
    progress['value'] = 0
    root.after_cancel(update_progress)

# API call in a separate thread
def api_call_thread(selected_file):
    global response_text
    progress["value"] = 20
    response_text = handle_WCJ_test_files(selected_file)
    root.after(50, on_api_call_complete)  # To update UI after API call

# Start the API call
def start_api_call():
    selected_test = test_select()
    if selected_test == 0:
        selected_file = file_select_WCJ()
        threading.Thread(target=api_call_thread, args=(selected_file,)).start()

# File selection with a delay
def delayed_file_selection():
    global selected_file
    selected_file = file_select_WCJ()
    if selected_file:  # Ensure the file was selected (not canceled)
        main_frame.pack_forget()
        show_progress_view()
        update_progress()
        threading.Thread(target=api_call_thread, args=(selected_file,)).start()

# Update the progress bar's value
def update_progress():
    current_value = progress["value"]
    new_value = current_value + 0.12
    progress["value"] = new_value
    root.after(100, update_progress)

# Main function to handle user selection
def main_program():
    selected_test = selected_test_var.get()
    if selected_test == "1: WCJ":
        root.after(100, delayed_file_selection)

# GUI Initialization
root = tk.Tk()
root.title("Auto-IEP")
root.geometry("800x600")

main_frame = tk.Frame(root)
main_frame.pack(pady=20)

label = tk.Label(main_frame, text="Supported tests are:")
label.pack(pady=10)

selected_test_var = tk.StringVar(root)
test_dropdown = ttk.Combobox(main_frame, textvariable=selected_test_var, values=["1: WCJ"])
test_dropdown.pack(pady=10)
test_dropdown.current(0)

process_button = tk.Button(main_frame, text="Select File and Process", command=main_program)
process_button.pack(pady=20)

# Create a progress bar outside the main frame (so it's hidden initially)
progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
progress["value"] = 0

spinner_label = tk.Label(root, text="Creating report :)")

def show_progress_view():
    progress.pack(pady=20)
    spinner_label.pack(pady=20)  # Display the spinner label under the progress bar

# Start tkinter loop
root.mainloop()
# In[ ]:




