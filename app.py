import streamlit as st
from modules.healy import Healy

# Initialize your AI fitness advisor
healy = Healy()

# Set page title
st.title("AI Fitness Advisor")

# Input text box for user question
input_text = st.text_input("Your fitness question")

# Button to submit the question
if st.button("Get Advice"):
    if input_text.strip() == "":
        st.warning("Please enter a fitness question before submitting.")
    else:
        # Generate AI response
        response = healy.generate_response(input_text)
        # Display the response
        st.text_area("AI Response", value=response, height=300, max_chars=None, key="response_area")
        