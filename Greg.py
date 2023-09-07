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
from python-docx import Document
import requests
import json
import  tkinter as tk
from tkinter import filedialog, ttk, simpledialog
import threading

#Constants

API_KEY = "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"
API_ENDPOINT = "https://api.openai.com/v1/chat/completions"

class Data_Extraction:
    def __init__(self, selected_file):
        self.selected_file = selected_file

    def handle_Teacher_Feedback_Form(self, REALSTUDENTNAME):
        teacherResponsesDf = pd.read_excel(self.selected_file, engine='openpyxl')
        placeholder_name = "Placeholder"
        sentences = []
        colNames = []
        for column in teacherResponsesDf.columns:
            if "Timestamp" not in column and "name" not in column and "Thank you" not in column and "Email" not in column and "Name" not in column and "Person Completing" not in column:
                colNames.append(column)
        for index, row in teacherResponsesDf.iterrows():
            teacherSpecificResponse =[]
            teacherSpecificResponse.append(f"$$Teacher respondent {index} answered the following questions with regards to {placeholder_name}.")
            for columnName in colNames:
                answerString = str(row[columnName])
                if answerString != "":
                    answerString.replace(REALSTUDENTNAME, "Placeholder")

                    teacherSpecificResponse.append(f"Question: {columnName} Answer: {answerString}".strip())
            teacherSpecificResponse.append("$$")
            teacherSpecificResponseJoined = ' '.join(map(str, teacherSpecificResponse))
            sentences.append(teacherSpecificResponseJoined)
        #Joining sentences for use in prompt
        dataForPrompt = ' '.join(map(str, sentences))
        return dataForPrompt

    def handle_WCJ_test_files(self):
        #Convert student file to tables
        doc = Document(self.selected_file)
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
        placeholder_name = "Placeholder"
        sentences = []
        for index, row in allScores.iterrows():
            dontskip = True
            subject_area = row['Cluster']
            proficiency = row['Proficiency']
            for idx, i in enumerate(sentences):  # Use enumerate to get the index and value of each item in the list
                if f"{placeholder_name} has {proficiency}" in i:
                    sentences[idx] = i.replace(".", f", {subject_area}.")  # Update the string in the list
                    dontskip = False
                    break
            if dontskip:
                sentence = f"{placeholder_name} has {proficiency} proficiency in {subject_area}."
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
        return dataForPrompt, REALSTUDENTNAME

class AI(Data_Extraction):
    def __init__(self, inputTypes, seperateBySubject):
        self.promptTuning = f"""Write an academic assesment report based on the following data collected
        from {inputTypes}, do not make it flowery.
        If teacher responses are present each response will be grouped by $$ if they are from the same teacher.
        Be sure to highlight relative strengths, also do not write in all caps.
        Avoid using run on sentences, try not to combine multiple subject areas into one sentence.
        Be certain to provide specific details.
        Be cautious to avoid any kind of linguistic mistakes.
        Do not mention of referring to the student as Placeholder, treat it as a name.
        There is no "the" classroom teacher, a student might have many teachers so use "a" instead of "the" if you refer to a teacher.
        Do not refer to a teacher as a number! You can just say according to a teacher respondent instead.
        Include as much information as possible while also maintaining an interesting writing style, we don't want information left out.
        """
        if seperateBySubject:
            self.promptTuning += " Clearly seperate between Reading Present Levels of Performance, Writing Present Levels of Performance, Math Present Levels of Performance, Communication Development Present Levels of Performance, and Other. Data:\n"
        else:
            self.promptTuning += "Data:\n"
        print(self.promptTuning)
    #Beginning of AI script
    #Openai interaction function
    def generate_report(self, dataForPrompt, REALSTUDENTNAME, model="gpt-4", temperature=0.5, max_tokens=None):
        PROMPT = ( f"{self.promptTuning}{dataForPrompt}")

        #Define how gpt should act
        messages=[
            {"role": "system", "content": "You are a special education teacher"},
            {"role": "user", "content": (f"{PROMPT}")},
        ]
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
            response_text = response.json()["choices"][0]["message"]["content"]
            response_text = response_text.replace("Placeholder", REALSTUDENTNAME)
            return (response_text)
        else:
            raise Exception(f"Error {response.status_code}: {response.text}")

# > GUI THINGS --------------------------------------------------------------------------
class ToolTip:
    def __init__(self, widget):
        self.widget = widget
        self.tip_window = None
        self.id = None
        self.x = self.y = 0
        self.last_item = None
        self.widget.bind("<Enter>", self.schedule)
        self.widget.bind("<Leave>", self.hide)
        self.widget.bind("<Motion>", self.on_motion)

    def on_motion(self, event):
        current_item = self.widget.nearest(event.y)

        if current_item != self.last_item:
            self.hide()
            self.last_item = current_item
        x, y, cx, cy = self.widget.bbox("active")
        x += self.widget.winfo_rootx() + 190  # Increase this value to move more to the right
        y += self.widget.winfo_rooty() + 25
        if not self.tip_window:
            self.show(event, x, y)
        else:  # If tooltip window is already active, update its position
            self.tip_window.wm_geometry(f"+{x}+{y}")

    def schedule(self, event):
        self.unschedule()
        self.id = self.widget.after(1000, self.show, event)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def show(self, event, x=None, y=None):
        self.unschedule()
        self.hide()
        if x is None or y is None:  # Check if x or y values are None
            return
        if self.widget.nearest(event.y) is not None:
            item = self.widget.get(self.widget.nearest(event.y))
            if item:
                self.tip_window = tw = tk.Toplevel(self.widget)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                label = tk.Label(tw, text=self.get_tooltip_text(item), justify=tk.LEFT, background="#ffffe0", relief=tk.SOLID, borderwidth=1, wraplength=200)
                label.pack(ipadx=1)

    def hide(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

    def get_tooltip_text(self, item):
    # You can customize your messages based on the item
        messages = {
            "0: Student Name": "FOR ADVANCED USERS: If you do not plan on using a standardized test then program will not automatically pull a name for the student, therefore you must input their first name manually. For example, if you only want to use the teacher response form and user input you should select this option. Incorrect inputs may result in the students REAL NAME being passed to the AI so use this with caution.",
            "1: Woodcock-Johnson IV": "Woodcock-Johnson IV score report with behavioral observations.",
            "2: Teacher Response Form": "Teacher response form in excel format.",
            "3: User Input": "Input information directly to application."
        }
        return messages.get(item, f"Unknown item: {item}")


class AutoIEPGUI:
    def __init__(self, root):
        self.root = root
        self.configure_root()
        self.output_checkbox = None
        self.create_ui_elements()
        self.initialize_ui_state()
        self.promptFinal = ""
        self.REALSTUDENTNAME = ""
        self.selected_test = []
        self.is_updating_progress = False

    def configure_root(self):
        self.root.title("Auto-IEP")
        self.root.geometry("800x600")

    def create_ui_elements(self):
        """Create the core UI components."""
        self.main_frame = self.create_main_frame()
        self.label = self.create_label()
        self.test_listbox = self.create_test_listbox()
        self.test_listbox_tooltip = ToolTip(self.test_listbox)
        self.process_button = self.create_process_button()
        self.output_checkbox = self.create_output_checkbox()
        self.progress = self.create_progress_bar()
        self.spinner_label = self.create_spinner_label()

    def initialize_ui_state(self):
        """Initialize the UI state."""
        self.text_frame = None
        self.text_widget = None
        self.result_title = None
        self.save_button = None
        self.new_report_button = None
        self.scrollbar = None
        self.response_text = ""

    # WIDGET CREATION METHODS
    def create_main_frame(self):
        frame = tk.Frame(self.root)
        frame.pack(pady=20)
        return frame

    def create_label(self):
        label = tk.Label(self.main_frame, text="Supported inputs are:")
        label.pack(pady=10)
        return label

    def create_test_listbox(self):
        listbox = tk.Listbox(self.main_frame, selectmode = "multiple", height=5)  # Height adjusted based on number of items.
        listbox.insert(tk.END, "0: Student Name", "1: Woodcock-Johnson IV", "2: Teacher Response Form", "3: User Input")
        listbox.pack(pady=10)
        return listbox

    def create_process_button(self):
        button = tk.Button(self.main_frame, text="Select File and Process", command=self.main_program)
        button.pack(pady=20)
        return button
        
    def create_output_checkbox(self):
        var = tk.BooleanVar()
        checkbox = tk.Checkbutton(self.main_frame, text="Seperate response by subject?", variable=var)
        checkbox.var = var  # Keep a reference to the BooleanVar
        checkbox.pack(pady=10)
        return checkbox

    def create_progress_bar(self):
        progress = ttk.Progressbar(self.root, orient="horizontal", length=300, mode="determinate")
        return progress

    def create_spinner_label(self):
        label = tk.Label(self.root, text="Creating report :)")
        return label

    def create_text_frame(self):
        self.text_frame = tk.Frame(self.root)
        self.text_frame.pack(pady=20)

    def create_result_title(self):
        self.result_title = tk.Label(self.text_frame, text="Generated report: ")
        self.result_title.pack()

    def create_scrollbar(self):
        self.scrollbar = tk.Scrollbar(self.text_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def create_text_widget(self):
        self.text_widget = tk.Text(self.text_frame, wrap=tk.WORD, yscrollcommand=self.scrollbar.set)
        self.text_widget.insert(tk.END, self.response_text)
        self.text_widget.pack(pady=20)
        self.scrollbar.config(command=self.text_widget.yview)

    def create_save_button(self):
        self.save_button = tk.Button(self.text_frame, text="Save Results", command=self.save_results)
        self.save_button.pack(pady=10)

    def create_new_report_button(self):
        self.new_report_button = tk.Button(self.text_frame, text="New Report", command=self.generate_new_report)
        self.new_report_button.pack(pady=10)

    def on_api_call_complete(self, response):
        # Hide progress view
        self.hide_all_widgets()

        # Store the response
        self.response_text = response

        # Create and display widgets
        self.create_text_frame()
        self.create_result_title()
        self.create_scrollbar()
        self.create_text_widget()
        self.create_save_button()
        self.create_new_report_button()

    def show_progress_view(self):
        self.progress.pack(pady=20)
        self.spinner_label.pack(pady=20)

    def hide_all_widgets(self):
        widgets_to_hide = [self.result_title, self.save_button, self.new_report_button, self.scrollbar,
                           self.progress, self.spinner_label, self.text_widget, self.text_frame]

        for widget in widgets_to_hide:
            if widget:
                widget.pack_forget()

    # UTILITY & LOGIC METHODS
    def file_select(self, title="Select a File"):
        """General file selector."""
        self.root.withdraw()  # hide main window
        file_path = filedialog.askopenfilename(title=title)
        return file_path

    def save_results(self):
        file_name = filedialog.asksaveasfilename(title="Save Results", filetypes=[("Text files", "*.txt"), ("All files", "*.*")], defaultextension=".txt")
        if file_name:
            with open(file_name, 'w') as file:
                file.write(self.response_text)
            messagebox.showinfo("Success", "Results saved successfully!")

    def main_program(self):
        selected_indices = self.test_listbox.curselection()  # Get the currently selected item's index
        if not selected_indices:  # Nothing selected
            return
        self.selected_test = []
        for index in selected_indices:
            self.selected_test.append(self.test_listbox.get(index))
            print(self.selected_test)
        if "0: Student Name" in self.selected_test:
            user_input = simpledialog.askstring("User Input", "Write the first name of student only (Case sensitive): ")
            self.REALSTUDENTNAME = user_input
            try:
                if self.REALSTUDENTNAME == "" or self.REALSTUDENTNAME == None:
                    raise Exception(f"Error 1: Student name is empty")
            except:
                quit_me()
                sys.exit()
        if "1: Woodcock-Johnson IV" in self.selected_test:
            selected_file = self.file_select("Select a WCJ File")
            if selected_file:
                # Run data extraction
                self.data_extraction_WCJ(selected_file)
        if "2: Teacher Response Form" in self.selected_test:
            selected_file = self.file_select("Select a Teacher Response Form File")
            if selected_file:
                # Run data extraction
                self.data_extraction_Teacher_Response_Form(selected_file)
        if "3: User Input" in self.selected_test:
            user_input = simpledialog.askstring("User Input", "This input will be given directly to the AI, the first name of the student will be obfuscated automatically but be careful to not include other identifying information (Student ID, last name, etc.): ")
            user_input.replace(self.REALSTUDENTNAME, "Placeholder")
            if user_input:
                self.promptFinal += "The following is direct user input from a teacher: " + user_input
        # Now make the AI call
        self.root.deiconify()  # show main window
        self.main_frame.pack_forget()
        self.show_progress_view()
        if not self.is_updating_progress:
            self.is_updating_progress = True
            self.update_progress()  # Start the progress update chain only if not already started
        try:
            if self.REALSTUDENTNAME == "" or self.REALSTUDENTNAME == None:
                raise Exception(f"Error 1: Student name is empty")
        except:
            quit_me()
            sys.exit()
        seperateBySubject = self.output_checkbox.var.get()
        print (seperateBySubject)
        threading.Thread(target=self.ai_call, args=(self.promptFinal, self.REALSTUDENTNAME, seperateBySubject)).start()

    def data_extraction_WCJ(self, selected_file):
        data_extractor = Data_Extraction(selected_file)
        promptSentencesWCJ, self.REALSTUDENTNAME = data_extractor.handle_WCJ_test_files()
        self.promptFinal = self.promptFinal + promptSentencesWCJ

    def data_extraction_Teacher_Response_Form(self, selected_file):
        data_extractor = Data_Extraction(selected_file)
        promptSentencesTeacherFeedbackForm = data_extractor.handle_Teacher_Feedback_Form(self.REALSTUDENTNAME)
        self.promptFinal = self.promptFinal + promptSentencesTeacherFeedbackForm

    def ai_call(self, promptFinal, REALSTUDENTNAME, seperateBySubject):
        aiObj = AI(self.selected_test, seperateBySubject)
        response = aiObj.generate_report(self.promptFinal, REALSTUDENTNAME)
        #non_thread_response = "Testing"
        self.root.after(10, self.on_api_call_complete, response)

    def update_progress(self):
        if self.progress["value"] >= 100:  # or any other maximum value you set for your progress bar
            self.is_updating_progress = False
            return
        current_value = self.progress["value"]
        new_value = current_value + 0.15
        self.progress["value"] = new_value
        self.root.after(100, self.update_progress)



    def generate_new_report(self):
        self.hide_all_widgets()
        self.response_text = ""
        self.progress["value"] = 0
        self.promptFinal = ""
        self.REALSTUDENTNAME = ""
        self.selected_test = []
        self.is_updating_progress = False
        self.main_frame.pack(pady=20)

# Execution:
def quit_me():
    print('quit')
    root.quit()
    root.destroy()

root = tk.Tk()
app = AutoIEPGUI(root)
root.protocol("WM_DELETE_WINDOW", quit_me)
root.mainloop()
# In[ ]:
